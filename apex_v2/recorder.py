"""Record the raw Kraken v2 WebSocket feed (book depth 10 + trades + heartbeats) to a text file.

One line per message:  <local receive time in ns>\t<raw json>
Local receive time is what the replay uses, so latency/staleness are measured the way
a live bot would see them.

    python3 -m apex_v2.recorder --seconds 600 --out data/kraken_YYYYMMDD.log
"""
from __future__ import annotations

import argparse
import json
import threading
import time

import websocket  # websocket-client

URL = "wss://ws.kraken.com/v2"
SYMBOLS = ["BTC/USD", "ETH/USD", "ETH/BTC"]


def record(seconds: float, out: str, depth: int = 10) -> int:
    n = {"msgs": 0}
    f = open(out, "a", buffering=1)

    def on_open(ws):
        for ch, extra in (("book", {"depth": depth}), ("trade", {"snapshot": False})):
            ws.send(json.dumps({"method": "subscribe",
                                "params": {"channel": ch, "symbol": SYMBOLS, **extra}}))

    def on_message(ws, message):
        f.write(f"{time.time_ns()}\t{message}\n")
        n["msgs"] += 1

    def on_error(ws, err):
        print("ws error:", err)

    ws = websocket.WebSocketApp(URL, on_open=on_open, on_message=on_message, on_error=on_error)
    threading.Timer(seconds, ws.close).start()
    ws.run_forever(ping_interval=20, ping_timeout=10)
    f.close()
    return n["msgs"]


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--seconds", type=float, default=600)
    ap.add_argument("--out", required=True)
    a = ap.parse_args()
    print(f"recorded {record(a.seconds, a.out)} messages -> {a.out}")
