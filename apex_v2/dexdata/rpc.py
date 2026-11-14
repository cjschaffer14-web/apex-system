"""Minimal JSON-RPC client (stdlib only): batching, retries, multi-endpoint. Read-only: it only
exposes calls the collector needs and refuses anything that can sign or send."""
from __future__ import annotations

import json
import time
import urllib.request
from typing import Any, List, Sequence, Tuple

READ_ONLY = {"eth_blockNumber", "eth_chainId", "eth_call", "eth_getBlockByNumber", "eth_getLogs",
              "eth_getTransactionByHash", "eth_getTransactionReceipt", "eth_getBlockByHash"}


class RpcError(Exception):
    pass


class Rpc:
    def __init__(self, urls: Sequence[str], timeout: float = 12.0, retries: int = 6, batch_size: int = 40):
        self.urls, self.timeout, self.retries, self.batch_size = list(urls), timeout, retries, batch_size
        self.calls = 0

    def _post(self, url: str, payload: Any) -> Any:
        req = urllib.request.Request(url, data=json.dumps(payload).encode(),
                                     headers={"content-type": "application/json", "user-agent": "apex-v2-dexdata/0.1"})
        with urllib.request.urlopen(req, timeout=self.timeout) as r:
            return json.loads(r.read().decode())

    def batch(self, calls: Sequence[Tuple[str, list]], endpoint: int = 0) -> List[Any]:
        for m, _ in calls:
            if m not in READ_ONLY:
                raise RpcError(f"method {m} not allowed (read-only client)")
        out: List[Any] = []
        for i in range(0, len(calls), self.batch_size):
            chunk = calls[i:i + self.batch_size]
            payload = [{"jsonrpc": "2.0", "id": j, "method": m, "params": p} for j, (m, p) in enumerate(chunk)]
            last = None
            for attempt in range(self.retries):
                try:
                    url = self.urls[(endpoint + attempt) % len(self.urls)]
                    resp = self._post(url, payload)
                    self.calls += 1
                    if isinstance(resp, dict):  # endpoint rejected the batch
                        raise RpcError(str(resp)[:200])
                    by_id = {r["id"]: r for r in resp}
                    res = []
                    for j in range(len(chunk)):
                        r = by_id[j]
                        if "error" in r:
                            msg = str(r["error"])[:200]
                            if "rate limit" in msg.lower() or "429" in msg:
                                raise RpcError("rate limited: " + msg)  # retry on the next endpoint
                            res.append(RpcError(msg))
                        else:
                            res.append(r["result"])
                    out.extend(res)
                    last = None
                    break
                except Exception as e:  # noqa: BLE001 - network/rate limit: back off, try next endpoint
                    last = e
                    time.sleep(0.3 * (attempt + 1))
            if last is not None:
                raise RpcError(f"batch failed: {last}")
        return out

    def call(self, method: str, params: list, endpoint: int = 0) -> Any:
        r = self.batch([(method, params)], endpoint)[0]
        if isinstance(r, Exception):
            raise r
        return r
