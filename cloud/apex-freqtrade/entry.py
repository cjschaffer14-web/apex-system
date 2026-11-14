"""Cloud Run Job entry. Only downloads public candles and runs backtests. No keys exist in this container."""
import glob
import json
import os
import subprocess
import time
import urllib.parse
import urllib.request
import zipfile

BUCKET = os.environ["APEX_BUCKET"]
SPECS = json.loads(os.environ["APEX_SPECS"])
DAYS = int(os.environ.get("APEX_DAYS", "120"))
FEES = (0.004, 0.008)  # the lab's 40 bps per unit traded, at 1x and 2x
ALLOWED = ("download-data", "backtesting")


def ft(command, *args, env=None):
    if command not in ALLOWED:
        raise SystemExit("refused: " + command)
    subprocess.run(["freqtrade", command, "--config", "/apex/config.json"] + list(args), check=True, env=env)


def token():
    req = urllib.request.Request("http://metadata.google.internal/computeMetadata/v1/instance/service-accounts/default/token", headers={"Metadata-Flavor": "Google"})
    with urllib.request.urlopen(req, timeout=20) as r:
        return json.load(r)["access_token"]


def upload(name, body):
    url = "https://storage.googleapis.com/upload/storage/v1/b/%s/o?uploadType=media&name=%s" % (BUCKET, urllib.parse.quote(name, safe=""))
    req = urllib.request.Request(url, data=body, headers={"Authorization": "Bearer " + token(), "Content-Type": "application/json"})
    urllib.request.urlopen(req, timeout=60).read()


def latest_result():
    newest = max(glob.glob("/freqtrade/user_data/backtest_results/*.zip"), key=os.path.getmtime)
    with zipfile.ZipFile(newest) as z:
        name = next(n for n in z.namelist() if n.endswith(".json") and "_config" not in n and "market" not in n)
        return json.loads(z.read(name))


def main():
    end = time.strftime("%Y%m%d", time.gmtime())
    start = time.strftime("%Y%m%d", time.gmtime(time.time() - DAYS * 86400))
    pairs = sorted({s["pair"] for s in SPECS})
    ft("download-data", "--timeframes", "1h", "--timerange", "%s-%s" % (time.strftime("%Y%m%d", time.gmtime(time.time() - (DAYS + 30) * 86400)), end), "--pairs", *pairs)
    out = []
    for spec in SPECS:
        for fee in FEES:
            env = dict(os.environ, APEX_SPEC=json.dumps(spec))
            ft("backtesting", "--strategy", "ApexCheck", "--strategy-path", "/apex", "--timerange", "%s-%s" % (start, end), "--fee", str(fee), "--pairs", spec["pair"], "--export", "trades", env=env)
            s = latest_result()["strategy"]["ApexCheck"]
            out.append(dict(spec, fee=fee, result={k: s.get(k) for k in ("profit_total", "max_drawdown_account", "total_trades", "wins", "market_change", "sharpe", "backtest_start", "backtest_end")}))
    upload("engines/freqtrade/%d.json" % int(time.time()), json.dumps({"engine": "freqtrade", "at": time.time(), "runs": out}).encode())
    print("APEX_DONE", len(out))


main()
