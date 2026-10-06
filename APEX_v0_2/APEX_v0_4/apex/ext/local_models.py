"""Local models (v0.4.1): the MLX organ that makes APEX's own models actually run.

Why they did not run in v0.4.0: three things were missing. MLX itself (APEX is standard-library only, so
nothing installed it); verified weights (no pinned model was downloaded); and an inference organ (v0.4.0
only checked readiness). v0.4.1 adds all three:

  * `setup_models.py` (run once on the Mac): a separate model environment (.venv) with a pinned
    mlx-vlm, and the catalog's models downloaded at pinned Hugging Face commits, every file verified
    against the hashes that commit publishes, then pinned in config/model_pins.json.
  * `model_worker.py`: the model runs in its own process with no keys (Proposal plane).
  * `LocalModelOrgan`: picks the model for the incubation band, loads only verified weights, keeps one
    model in memory at a time, records every inference (hashes, not text) in the ledger, and passes the
    output through the membrane on the `local_model` channel (trust 0.5: it can propose, never authorize).

Catalog for the owner's MacBook Pro (M5 Pro, 24 GB unified memory), multimodal (text + image), checked
2 Oct 2026:
  fast  Qwen3.5-9B, 4-bit   ~5.6 GB  used in WARM, INCUBATING and ACCELERATED
  deep  Qwen3.8-27B, 4-bit  ~15.0 GB used only in ACCELERATED (machine idle, on power); never both at once
"""
from __future__ import annotations
import hashlib, json, os, platform, re, subprocess, sys, time, threading
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

MLX_VLM_VERSION = "0.7.4"          # pinned; PyPI latest on 2 Oct 2026 (released 28 Sep 2026)

CATALOG: dict[str, dict] = {
    "fast": {"repo": "mlx-community/Qwen3.5-9B-4bit", "revision": "8b2b98c00a6b4d291155e4890773ca8f769aee53",
             "size_gb": 5.6, "kind": "multimodal", "license": "Apache-2.0", "min_ram_gb": 16,
             "bands": ("WARM", "INCUBATING", "ACCELERATED")},
    "deep": {"repo": "mlx-community/Qwen3.8-27B-4bit", "revision": "10c35caafbb80f7dc6a7a432cdd11af10a6d4818",
             "size_gb": 15.0, "kind": "multimodal", "license": "Apache-2.0", "min_ram_gb": 24,
             "bands": ("ACCELERATED",)},
}


def model_dir(home: Path, role: str) -> Path:
    return home / "models" / role / CATALOG[role]["repo"].split("/")[-1]


def roles_for_ram(ram_gb: float) -> list[str]:
    return [r for r in ("fast", "deep") if ram_gb >= CATALOG[r]["min_ram_gb"]]


def apple_silicon() -> bool:
    return platform.system() == "Darwin" and platform.machine() == "arm64"


def ram_gb() -> float:
    try:
        return int(subprocess.check_output(["sysctl", "-n", "hw.memsize"], text=True).strip()) / 2 ** 30
    except Exception:  # noqa: BLE001
        try:
            return os.sysconf("SC_PAGE_SIZE") * os.sysconf("SC_PHYS_PAGES") / 2 ** 30
        except (ValueError, OSError, AttributeError):
            return 0.0


# --- verification against the pinned commit ----------------------------------------------------------

def git_blob_sha1(data: bytes) -> str:
    return hashlib.sha1(b"blob %d\0" % len(data) + data).hexdigest()


def file_hashes(path: Path) -> tuple[str, str | None]:
    """(sha256, git blob sha1 for files under 50 MB). Streams large files."""
    h = hashlib.sha256()
    size = path.stat().st_size
    small = bytearray() if size < 50 * 2 ** 20 else None
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
            if small is not None:
                small += chunk
    return h.hexdigest(), git_blob_sha1(bytes(small)) if small is not None else None


def verify_file(path: Path, meta: dict) -> tuple[bool, str, str]:
    """Check one downloaded file against the commit's metadata: LFS files by SHA-256, the rest by git blob id."""
    if not path.exists():
        return False, "missing", ""
    if path.stat().st_size != int(meta.get("size", -1)):
        return False, f"size {path.stat().st_size} != {meta.get('size')}", ""
    sha256, blob = file_hashes(path)
    lfs = (meta.get("lfs") or {}).get("sha256")
    if lfs:
        return sha256 == lfs, "lfs sha256 " + ("matches" if sha256 == lfs else "MISMATCH"), sha256
    if meta.get("blobId"):
        ok = blob == meta["blobId"]
        return ok, "git blob id " + ("matches" if ok else "MISMATCH"), sha256
    return False, "no published hash to check against", sha256


def folder_digest(files: dict[str, str]) -> str:
    """Digest of a pinned model: SHA-256 over sorted 'name:sha256' lines."""
    return hashlib.sha256("\n".join(f"{k}:{files[k]}" for k in sorted(files)).encode()).hexdigest()


# --- the organ ----------------------------------------------------------------------------------------

THINK = re.compile(r"<think>.*?</think>", re.S)


class WorkerClient:
    """One model worker process; JSON lines over a pipe, with a timeout per request."""

    def __init__(self, cmd: list[str], cwd: Path, timeout: float = 600.0) -> None:
        env = dict(os.environ, PYTHONPATH=str(cwd))
        self.proc = subprocess.Popen(cmd, cwd=str(cwd), env=env, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                     stderr=subprocess.DEVNULL, text=True, bufsize=1)
        self.timeout = timeout

    def call(self, req: dict, timeout: float | None = None) -> dict:
        try:
            self.proc.stdin.write(json.dumps(req) + "\n")
            self.proc.stdin.flush()
        except (BrokenPipeError, OSError):
            pass                                   # a worker that failed at start has already written its error
        box: list[str] = []
        reader = threading.Thread(target=lambda: box.append(self.proc.stdout.readline()), daemon=True)
        reader.start()
        reader.join(timeout or self.timeout)
        if not box or not box[0]:
            self.close()
            return {"ok": False, "error": "worker timed out or exited"}
        return json.loads(box[0])

    def close(self) -> None:
        if self.proc.poll() is None:
            try:
                self.proc.stdin.write(json.dumps({"op": "quit"}) + "\n")
                self.proc.stdin.flush()
                self.proc.wait(5)
            except Exception:  # noqa: BLE001
                self.proc.kill()
                self.proc.wait(5)
        for pipe in (self.proc.stdin, self.proc.stdout):
            try:
                pipe.close()
            except Exception:  # noqa: BLE001
                pass


@dataclass
class Answer:
    text: str
    role: str
    tokens: int
    tps: float
    seconds: float
    observation: str | None


class LocalModelOrgan:
    def __init__(self, home: Path, pins: Callable[[], list[dict]], record: Callable[[str, dict], Any],
                 ingest: Callable[[Any, str, str], Any], python: str | None = None, backend: str = "mlx",
                 require_apple_silicon: bool = True) -> None:
        self.home = home
        self._pins, self._record, self._ingest = pins, record, ingest
        venv = home / ".venv" / "bin" / "python"
        self.python = python or (str(venv) if venv.exists() else sys.executable)
        self.backend = backend
        self.require_apple_silicon = require_apple_silicon
        self.worker: WorkerClient | None = None
        self.loaded: str | None = None
        self.failed: dict[str, str] = {}

    # -- readiness ------------------------------------------------------------------------------
    def platform_ok(self) -> bool:
        return apple_silicon() or not self.require_apple_silicon

    def verified(self) -> dict[str, dict]:
        return {p["role"]: p for p in self._pins() if p.get("role") in CATALOG and p.get("verified")}

    def ready(self, role: str | None = None) -> bool:
        ok = {r for r in self.verified() if r not in self.failed}
        return self.platform_ok() and (bool(ok) if role is None else role in ok)

    def role_for(self, band: str) -> str | None:
        for role in ("deep", "fast"):
            if band in CATALOG[role]["bands"] and self.ready(role):
                return role
        return None

    def status(self) -> dict:
        return {"apple_silicon": apple_silicon(), "python": self.python, "backend": self.backend,
                "verified": sorted(self.verified()), "loaded": self.loaded, "failed": dict(self.failed),
                "mlx_vlm": MLX_VLM_VERSION}

    # -- running ----------------------------------------------------------------------------------------
    def _ensure(self, role: str) -> None:
        if self.loaded == role and self.worker:
            return
        pin = self.verified().get(role)
        if pin is None:
            raise RuntimeError(f"{role}: no verified, pinned weights (run setup_models.py)")
        if self.worker is None:
            self.worker = WorkerClient([self.python, "-m", "apex.ext.model_worker", "--backend", self.backend],
                                       Path(__file__).resolve().parents[2])
            hello = self.worker.call({"op": "ping"}, timeout=120)
            if not hello.get("ok"):
                self.worker.close()
                self.worker = None
                raise RuntimeError(hello.get("error", "model worker unavailable"))
            self._record("ModelRuntimeStarted", {"backend": hello.get("backend"), "versions": hello.get("versions")})
        if self.loaded:
            self.worker.call({"op": "unload"})               # one model in memory at a time
        res = self.worker.call({"op": "load", "path": str(self.home / pin["path"])})
        if not res.get("ok"):
            raise RuntimeError(res.get("error", "load failed"))
        self.loaded = role
        self._record("ModelLoaded", {"role": role, "repo": pin.get("source"), "sha256": pin.get("sha256"),
                                     "seconds": res.get("seconds")})

    def ask(self, prompt: str, role: str = "fast", images: list[str] | None = None, max_tokens: int = 768,
            purpose: str = "") -> Answer:
        """Run one inference. Raises RuntimeError if the role cannot run; the caller decides what to do."""
        try:
            self._ensure(role)
            res = self.worker.call({"op": "generate", "prompt": prompt, "images": list(images or []),
                                    "max_tokens": max_tokens})
            if not res.get("ok"):
                raise RuntimeError(res.get("error", "generation failed"))
        except RuntimeError as e:
            self.failed[role] = str(e)[:300]
            self._record("ModelRuntimeError", {"role": role, "error": self.failed[role]})
            raise
        raw = res.get("text", "")
        text = THINK.sub("", raw).strip()
        obs = self._ingest(text, "local_model", f"model:{role}")
        self._record("ModelInference", {
            "role": role, "purpose": purpose, "prompt_sha256": hashlib.sha256(prompt.encode()).hexdigest(),
            "output_sha256": hashlib.sha256(text.encode()).hexdigest(), "images": len(images or []),
            "tokens": res.get("tokens"), "tps": res.get("tps"), "seconds": res.get("seconds"),
            "observation": getattr(obs, "id", None)})
        return Answer(text, role, int(res.get("tokens") or 0), float(res.get("tps") or 0.0),
                      float(res.get("seconds") or 0.0), getattr(obs, "id", None))

    def close(self) -> None:
        if self.worker:
            self.worker.close()
        self.worker, self.loaded = None, None


# --- tasks the organism gives its local models -------------------------------------------------------------

def self_model_prompt(sm: dict, limit: int = 60) -> str:
    mods = [m for m in sm["modules"] if m["module"].startswith("apex.ext")][:limit]
    lines = [f"- {m['module']} ({m['plane']}{', protected' if m['protected'] else ''}): {m['summary'][:110]}"
             for m in mods]
    return ("You are reading a map of your own source code (read-only). Modules:\n" + "\n".join(lines) +
            "\n\nIn at most 8 short bullets: describe how proposals, authority and actuation fit together, then "
            "name the two weakest points you see. Facts only from the map.")


def paper_qa_prompt(paper: str, question: str) -> str:
    return (f"Answer from the paper only, in one or two sentences, quoting exact figures and terms.\n\n"
            f"PAPER:\n{paper}\n\nQUESTION: {question}")


def score_answer(answer: str, expected: tuple[str, ...]) -> bool:
    return all(e.lower() in answer.lower() for e in expected)


def research_note_prompt(stats: dict) -> str:
    rows = "\n".join(f"- {pair}: " + ", ".join(f"{k}={v}" for k, v in s.items()) for pair, s in stats.items())
    return ("These are descriptive statistics of daily crypto prices from a validated local corpus:\n" + rows +
            "\n\nPropose at most three testable hypotheses for a walk-forward simulation. For each: the signal, "
            "the expected effect, and what result would falsify it. No trading advice.")
