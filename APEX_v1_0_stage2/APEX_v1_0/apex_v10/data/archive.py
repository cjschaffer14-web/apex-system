"""Raw payload archive: every byte a source adapter reads is stored once, by SHA-256, with its request.

Two modes, same code path for the adapters:
  online  fetch over HTTPS (GET only, polite spacing, retries on 429/5xx/timeouts), store the payload gzip-
          compressed (deterministic: mtime 0) under <root>/<source>/<sha256>.gz and append one manifest line.
  raw     never touch the network; serve each request from the archive by its request key, verify the SHA-256.
          Rebuilding from the archive reproduces the v1.0 database content exactly on any machine.
"""
from __future__ import annotations

import gzip
import hashlib
import io
import json
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

USER_AGENT = "APEX-v1.0-research/stage1 (public market and government data; research only)"


@dataclass(frozen=True)
class Payload:
    source: str
    url: str
    body: bytes
    sha256: str
    retrieved_ts: int
    status: int


def request_key(url: str) -> str:
    return hashlib.sha256(url.encode()).hexdigest()


def gzip_deterministic(data: bytes) -> bytes:
    buf = io.BytesIO()
    with gzip.GzipFile(fileobj=buf, mode="wb", compresslevel=9, mtime=0) as g:
        g.write(data)
    return buf.getvalue()


class RawArchive:
    def __init__(self, root: Path, mode: str = "raw", clock=time.time, sleep=time.sleep, opener=None) -> None:
        if mode not in ("online", "raw"):
            raise ValueError("mode must be 'online' or 'raw'")
        self.root, self.mode = Path(root), mode
        self.manifest_path = self.root / "MANIFEST.jsonl"
        self._clock, self._sleep = clock, sleep
        self._opener = opener or self._urlopen
        self._last_call: dict[str, float] = {}
        self._index: dict[str, dict] = {}
        if self.manifest_path.exists():
            for line in self.manifest_path.read_text().splitlines():
                if line.strip():
                    rec = json.loads(line)
                    self._index[rec["request_key"]] = rec
        if mode == "raw" and not self._index:
            raise FileNotFoundError(f"no raw archive manifest at {self.manifest_path}")
        self.calls: list[str] = []

    # -- network -------------------------------------------------------------------------------------------------
    @staticmethod
    def _urlopen(url: str, timeout: float) -> tuple[int, bytes]:
        req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT, "Accept": "*/*"})
        try:
            with urllib.request.urlopen(req, timeout=timeout) as r:
                return r.status, r.read()
        except urllib.error.HTTPError as e:
            return e.code, e.read() if hasattr(e, "read") else b""

    def _fetch(self, source: str, url: str, spacing_s: float, timeout: float, retries: int) -> tuple[int, bytes]:
        last = self._last_call.get(source, 0.0)
        wait = spacing_s - (self._clock() - last)
        if wait > 0:
            self._sleep(wait)
        status, body = 0, b""
        for attempt in range(retries + 1):
            try:
                status, body = self._opener(url, timeout)
            except (urllib.error.URLError, TimeoutError, OSError) as e:
                status, body = 599, str(e).encode()
            self._last_call[source] = self._clock()
            if status in (429, 500, 502, 503, 504, 599) and attempt < retries:
                self._sleep(min(60.0, 5.0 * 2 ** attempt))
                continue
            break
        return status, body

    # -- public --------------------------------------------------------------------------------------------------
    def get(self, source: str, url: str, spacing_s: float = 1.0, timeout: float = 90.0, retries: int = 4) -> Payload:
        key = request_key(url)
        self.calls.append(url)
        if self.mode == "raw":
            rec = self._index.get(key)
            if rec is None:
                raise KeyError(f"request not in the raw archive: {url}")
            body = gzip.decompress((self.root / rec["path"]).read_bytes())
            digest = hashlib.sha256(body).hexdigest()
            if digest != rec["sha256"]:
                raise ValueError(f"archived payload corrupted for {url}")
            return Payload(source, url, body, digest, rec["retrieved_ts"], rec["status"])
        status, body = self._fetch(source, url, spacing_s, timeout, retries)
        if status != 200:
            raise RuntimeError(f"{source}: HTTP {status} for {url}: {body[:200]!r}")
        digest = hashlib.sha256(body).hexdigest()
        rel = f"{source}/{digest}.gz"
        path = self.root / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        if not path.exists():
            path.write_bytes(gzip_deterministic(body))
        retrieved = int(self._clock())
        rec = {"request_key": key, "source": source, "url": url, "sha256": digest, "bytes": len(body),
               "path": rel, "retrieved_ts": retrieved, "status": status}
        self._index[key] = rec
        with self.manifest_path.open("a") as f:
            f.write(json.dumps(rec, sort_keys=True) + "\n")
        return Payload(source, url, body, digest, retrieved, status)

    def lookup(self, url: str) -> Optional[dict]:
        return self._index.get(request_key(url))
