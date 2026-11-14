"""Public data receipts only. No trading client or credential ingestion."""
import concurrent.futures
import hashlib
import json
import math
import os
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

ROOT = Path(__file__).parent
MANIFEST = json.loads((ROOT / 'manifest.json').read_text())
REVISION = hashlib.sha256(Path(__file__).read_bytes()).hexdigest()
MAX_BYTES = 1024 * 1024
MINUTE_WINDOW_COUNT = 180
if hashlib.sha256(json.dumps(MANIFEST['markets'], separators=(',', ':')).encode()).hexdigest() != MANIFEST['sha']:
    raise ValueError('market manifest integrity mismatch')

def http_json(url, method='GET', data=None, headers=None, timeout=4):
    req = urllib.request.Request(url, data=data, method=method, headers=headers or {})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        body = r.read(MAX_BYTES + 1)
        if len(body) > MAX_BYTES:
            raise ValueError('response size limit')
        return json.loads(body)

def receipt_name(slot):
    return f"receipts/{REVISION[:12]}/{MANIFEST['sha'][:12]}/{slot}.json"

def candle_count(interval):
    return MINUTE_WINDOW_COUNT if interval == 60 else 3

def missing_timestamps(rows, interval, end, count):
    observed = {int(row[0]) for row in rows}
    return [ts for ts in range(end-count*interval, end, interval) if ts not in observed]

def validate(rows, interval, end, count=3, allow_gaps=False):
    result = {}
    for row in rows:
        if len(row) != 6 or any(not math.isfinite(float(x)) for x in row):
            raise ValueError('malformed candle')
        ts, low, high, op, cl, vol = row
        if ts % interval or not 0 < low <= min(op, cl) <= max(op, cl) <= high or vol < 0:
            raise ValueError('invalid candle')
        if end - count * interval <= ts < end:
            if int(ts) in result and result[int(ts)] != row:
                raise ValueError('conflicting duplicate candle')
            result[int(ts)] = row
    expected = list(range(end - count * interval, end, interval))
    if not result or (not allow_gaps and sorted(result) != expected):
        raise ValueError('missing real completed candles')
    return [result[x] for x in sorted(result)]

def sample(item, now):
    pair, interval = item
    # Leave one minute for the exchange to publish newly completed minute bars.
    end = int(now) // interval * interval - (60 if interval == 60 else 0)
    count = candle_count(interval)
    def stamp(t): return time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime(t))
    query = urllib.parse.urlencode({'granularity': interval, 'start': stamp(end-count*interval), 'end': stamp(end)})
    rows = http_json('https://api.exchange.coinbase.com/products/' + pair + '/candles?' + query,
                     headers={'User-Agent': 'APEX-public-cloud/1.0'})
    candles = validate(rows, interval, end, count, allow_gaps=interval == 60)
    missing = missing_timestamps(candles, interval, end, count)
    return {'pair': pair, 'interval_seconds': interval, 'candles': candles,
            'received_ns': time.time_ns(), 'latest_completed_end': end,
            'window_count': count, 'missing_timestamps': missing,
            'coverage_status': 'gapped' if missing else 'complete'}

def validate_sample(sample):
    interval = sample['interval_seconds']
    count = candle_count(interval)
    if sample['window_count'] != count:
        raise ValueError('unexpected candle window')
    candles = validate(sample['candles'], interval, sample['latest_completed_end'],
                       count, allow_gaps=interval == 60)
    missing = missing_timestamps(candles, interval, sample['latest_completed_end'], count)
    if sample['missing_timestamps'] != missing:
        raise ValueError('incorrect gap accounting')
    if sample['coverage_status'] != ('gapped' if missing else 'complete'):
        raise ValueError('incorrect coverage status')

class Store:
    def __init__(self):
        expected = os.environ['EXPECTED_PROJECT']
        headers = {'Metadata-Flavor': 'Google'}
        base = 'http://metadata.google.internal/computeMetadata/v1/'
        req = urllib.request.Request(base + 'project/project-id', headers=headers)
        with urllib.request.urlopen(req, timeout=3) as r: actual = r.read(200).decode()
        if actual != expected: raise ValueError('cloud project identity mismatch')
        token = http_json(base + 'instance/service-accounts/default/token', headers=headers)['access_token']
        self.headers = {'Authorization': 'Bearer ' + token, 'Content-Type': 'application/json'}
        self.bucket = os.environ['BUCKET']
        if not self.bucket.startswith(expected + '-apex-public-'): raise ValueError('bucket identity mismatch')
    def put(self, name, document, generation):
        query = urllib.parse.urlencode({'uploadType': 'media', 'name': name, 'ifGenerationMatch': generation})
        url = 'https://storage.googleapis.com/upload/storage/v1/b/' + self.bucket + '/o?' + query
        payload = json.dumps(document, separators=(',', ':'), allow_nan=False).encode()
        if len(payload) > MAX_BYTES: raise ValueError('receipt size limit')
        return http_json(url, 'POST', payload, self.headers)['generation']
    def get(self, name):
        url = 'https://storage.googleapis.com/storage/v1/b/' + self.bucket + '/o/' + urllib.parse.quote(name, safe='') + '?alt=media'
        return http_json(url, headers=self.headers)

def healthy(doc, now):
    return (doc.get('state') == 'fresh' and doc.get('manifest_sha') == MANIFEST['sha']
            and doc.get('revision') == REVISION and 0 <= now - doc.get('finished_ts', 0) <= 1800
            and len(doc.get('samples', [])) == len(MANIFEST['markets']))

def collect(store, now=None):
    now = time.time() if now is None else now
    slot = int(now) // 1200 * 1200
    name = receipt_name(slot)
    document = {'state': 'collecting', 'slot': slot, 'started_ts': now, 'revision': REVISION,
                'manifest_sha': MANIFEST['sha'], 'source': 'coinbase/exchange/public',
                'mode': 'read_only_public_collection',
                'coverage': 'three hourly/daily bars plus 180-minute recovery windows; explicit gaps; no ticks or fills'}
    try: generation = store.put(name, document, 0)
    except urllib.error.HTTPError as e:
        if e.code == 412: return {'state': 'duplicate_skipped', 'slot': slot}
        raise
    samples, errors = [], []
    # Three concurrent requests, paced in batches below Coinbase public rate limits.
    with concurrent.futures.ThreadPoolExecutor(max_workers=3) as pool:
        markets = MANIFEST['markets']
        for offset in range(0, len(markets), 3):
            futures = {pool.submit(sample, item, now): item for item in markets[offset:offset+3]}
            for f, item in futures.items():
                try: samples.append(f.result())
                except Exception as e: errors.append({'pair': item[0], 'interval_seconds': item[1], 'error_type': type(e).__name__})
            if offset+3 < len(markets): time.sleep(1)
    document.update(state='fresh' if not errors else 'blocked', samples=samples, errors=errors,
                    finished_ts=time.time(), quality='gapped' if any(s.get('missing_timestamps') for s in samples) else 'complete')
    store.put(name, document, generation)
    return {k: document[k] for k in ('state', 'slot', 'finished_ts', 'errors', 'revision')}

def monitor(store, now=None):
    now = time.time() if now is None else now
    slot = int(now) // 1200 * 1200
    for candidate in (slot, slot-1200):
        try:
            doc = store.get(receipt_name(candidate))
            if healthy(doc, now): return {'state': 'fresh', 'slot': candidate, 'revision': REVISION}
            if doc.get('state') == 'blocked': break
        except urllib.error.HTTPError as e:
            if e.code != 404: raise
    return {'state': 'stale_or_failed', 'severity': 'ERROR', 'slot': slot, 'revision': REVISION}

if __name__ == '__main__':
    result = monitor(Store()) if os.environ.get('MODE') == 'monitor' else collect(Store())
    print(json.dumps(result, separators=(',', ':')))
    if result['state'] in ('blocked', 'stale_or_failed'): raise SystemExit(1)
