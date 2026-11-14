"""Bound Calendar notifications to watches; publish at least once.

No Calendar credentials or content. inbox.py handles durable duplicate receipts:
HTTP publication and Pub/Sub acknowledgement are not one atomic operation.
"""
import hashlib
import hmac
import json
import math
import os
import re
import time
import urllib.request
from base64 import b64encode
from http.server import BaseHTTPRequestHandler, HTTPServer

PROJECT = os.environ.get("GOOGLE_CLOUD_PROJECT", "alert-maker-509913-m7")
TOPIC = os.environ.get("APEX_TOPIC", "apex-coordinator")


def header(headers, name):
    return next((v for k, v in headers.items() if k.lower() == name.lower()), "")


def authorized(headers, token):
    supplied = header(headers, "X-Goog-Channel-Token")
    return (isinstance(token, str) and 1 <= len(token) <= 256
            and isinstance(supplied, str) and 1 <= len(supplied) <= 256
            and hmac.compare_digest(supplied.encode(), token.encode()))


def registry(raw):
    value = json.loads(raw)
    if not isinstance(value, dict) or value.get("version") != 2:
        raise ValueError("watch registry version required")
    rows = value.get("channels")
    if not isinstance(rows, list) or not 1 <= len(rows) <= 16:
        raise ValueError("bounded watch registry required")
    seen = set()
    for row in rows:
        if not isinstance(row, dict): raise ValueError("watch record required")
        cid = row.get("id")
        if not isinstance(cid, str) or not re.fullmatch(r"[A-Za-z0-9_-]{1,64}", cid) or cid in seen:
            raise ValueError("unique channel ID required")
        seen.add(cid)
        expiry = row.get("expires_at")
        if isinstance(expiry, bool) or not isinstance(expiry, (int, float)) or not math.isfinite(expiry) or expiry <= 0:
            raise ValueError("watch expiry required")
        if row.get("phase") not in {"active", "pending"}: raise ValueError("watch phase required")
        if row["phase"] == "active":
            rid = row.get("resource_id")
            if not isinstance(rid, str) or not re.fullmatch(r"[A-Za-z0-9_+=./~-]{1,256}", rid):
                raise ValueError("watch resource ID required")
    return rows


def event_for(headers, now):
    cid = header(headers, "X-Goog-Channel-ID")
    rid = header(headers, "X-Goog-Resource-ID")
    number = header(headers, "X-Goog-Message-Number")
    state = header(headers, "X-Goog-Resource-State")
    key = hashlib.sha256((cid + "\0" + rid).encode()).hexdigest()
    return {"schema": "calendar-notification/2", "event": "calendar.watch_sync" if state == "sync" else "calendar.changed",
            "state": state, "channel_key": key, "message_number": number,
            "delivery_id": hashlib.sha256((key + ":" + number).encode()).hexdigest(),
            "observed_at": now, "paper_only": True}


def access_token():
    req = urllib.request.Request("http://metadata.google.internal/computeMetadata/v1/instance/service-accounts/default/token", headers={"Metadata-Flavor": "Google"})
    with urllib.request.urlopen(req, timeout=10) as r:
        return json.load(r)["access_token"]


def publish(event):
    url = "https://pubsub.googleapis.com/v1/projects/%s/topics/%s:publish" % (PROJECT, TOPIC)
    body = {"messages": [{"data": b64encode(json.dumps(event).encode()).decode()}]}
    req = urllib.request.Request(url, data=json.dumps(body).encode(), headers={"Authorization": "Bearer " + access_token(), "Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=15) as response:
        result = json.load(response)
    if not isinstance(result.get("messageIds"), list) or len(result["messageIds"]) != 1 or not result["messageIds"][0]:
        raise RuntimeError("publish acknowledgement absent")


def receive(path, headers, token, raw_registry, publisher, now):
    if path != "/push": return 404
    if not authorized(headers, token): return 403
    try: rows = registry(raw_registry)
    except (TypeError, ValueError): return 503
    cid = header(headers, "X-Goog-Channel-ID")
    row = next((r for r in rows if r["id"] == cid), None)
    if row is None: return 403
    if now >= row["expires_at"]: return 410
    # sync can arrive before watch returns its resource ID. Retry until the
    # response is durably saved and the registry has been finalized.
    if row["phase"] == "pending": return 503
    if header(headers, "X-Goog-Resource-ID") != row["resource_id"]: return 403
    state = header(headers, "X-Goog-Resource-State")
    number = header(headers, "X-Goog-Message-Number")
    if state not in {"sync", "exists", "not_exists"}: return 400
    if not isinstance(number, str) or not re.fullmatch(r"[1-9][0-9]{0,19}", number): return 400
    if state == "sync" and number != "1": return 400
    try: publisher(event_for(headers, now))
    except Exception: return 503  # Retry with stable delivery_id, even for ambiguous publication.
    return 204


class Handler(BaseHTTPRequestHandler):
    def do_POST(self):
        status = receive(self.path, self.headers, os.environ.get("APEX_CHANNEL_TOKEN"),
                         os.environ.get("APEX_CHANNELS_JSON", ""), publish, time.time())
        if status == 204:
            event = event_for(self.headers, time.time())
            print(json.dumps({"event":"calendar.notification.accepted", "state":event["state"], "delivery_id":event["delivery_id"]}), flush=True)
        self.send_response(status)
        self.end_headers()

    def do_GET(self):
        self.send_response(200 if self.path in {"/", "/health"} else 404)
        self.end_headers()
        self.wfile.write(b"ok" if self.path in {"/", "/health"} else b"")

    def log_message(self, *args): pass


if __name__ == "__main__":
    HTTPServer(("", int(os.environ.get("PORT", "8080"))), Handler).serve_forever()
