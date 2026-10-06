"""Local model worker (v0.4.1): runs one MLX vision-language model in its own process.

APEX's core stays standard-library only and never imports MLX. This worker runs under the model
environment's Python (`.venv/bin/python`, created by setup_models.py), holds no keys, and talks to the
organism over stdin/stdout, one JSON object per line:

    {"op": "ping"}                                     -> {"ok": true, "backend": "mlx", "versions": {...}}
    {"op": "load", "path": "models/fast/..."}          -> {"ok": true, "seconds": 3.1}
    {"op": "generate", "prompt": "...", "images": [], "max_tokens": 512}
                                                       -> {"ok": true, "text": "...", "tokens": 120, "tps": 41.2}
    {"op": "unload"} / {"op": "quit"}

Everything the model writes is Proposal-plane data: the organism passes it through the membrane, and
it can never authorize anything. Backends: "mlx" (mlx-vlm on Apple silicon) and "echo" (tests).
"""
from __future__ import annotations
import argparse, json, sys, time


class EchoBackend:
    """Deterministic stand-in used by the tests (no model, no MLX)."""

    name = "echo"

    def versions(self) -> dict:
        return {"backend": "echo"}

    def load(self, path: str) -> None:
        self.path = path

    def generate(self, prompt: str, images: list[str], max_tokens: int) -> dict:
        words = prompt.split()
        text = f"<think>checking</think>echo({len(words)} words, {len(images)} images): " + " ".join(words[-12:])
        return {"text": text, "tokens": min(max_tokens, len(words)), "tps": 1000.0}

    def unload(self) -> None:
        self.path = None


class MlxBackend:
    name = "mlx"

    def __init__(self) -> None:
        import mlx_vlm  # noqa: F401  (fails fast if the model environment is missing)
        self.model = self.processor = self.config = None

    def versions(self) -> dict:
        from importlib.metadata import version
        out = {}
        for pkg in ("mlx", "mlx-vlm", "mlx-lm"):
            try:
                out[pkg] = version(pkg)
            except Exception:  # noqa: BLE001
                pass
        return out

    def load(self, path: str) -> None:
        from mlx_vlm import load
        from mlx_vlm.utils import load_config
        self.unload()
        self.model, self.processor = load(path)
        self.config = load_config(path)

    def generate(self, prompt: str, images: list[str], max_tokens: int) -> dict:
        from mlx_vlm import generate
        from mlx_vlm.prompt_utils import apply_chat_template
        if self.model is None:
            raise RuntimeError("no model loaded")
        formatted = apply_chat_template(self.processor, self.config, prompt, num_images=len(images))
        out = generate(self.model, self.processor, formatted, images or None, max_tokens=max_tokens, verbose=False)
        text = getattr(out, "text", out)
        return {"text": str(text), "tokens": int(getattr(out, "generation_tokens", 0) or 0),
                "tps": float(getattr(out, "generation_tps", 0.0) or 0.0),
                "peak_memory_gb": float(getattr(out, "peak_memory", 0.0) or 0.0)}

    def unload(self) -> None:
        self.model = self.processor = self.config = None
        try:
            import gc
            import mlx.core as mx
            gc.collect()
            mx.clear_cache()
        except Exception:  # noqa: BLE001
            pass


def serve(backend) -> None:
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            req = json.loads(line)
            op = req.get("op")
            t0 = time.perf_counter()
            if op == "ping":
                res = {"ok": True, "backend": backend.name, "versions": backend.versions()}
            elif op == "load":
                backend.load(req["path"])
                res = {"ok": True, "seconds": round(time.perf_counter() - t0, 2)}
            elif op == "generate":
                res = {"ok": True, **backend.generate(str(req.get("prompt", "")), list(req.get("images") or []),
                                                      int(req.get("max_tokens", 512))),
                       "seconds": round(time.perf_counter() - t0, 2)}
            elif op == "unload":
                backend.unload()
                res = {"ok": True}
            elif op == "quit":
                print(json.dumps({"ok": True}), flush=True)
                return
            else:
                res = {"ok": False, "error": f"unknown op {op!r}"}
        except Exception as e:  # noqa: BLE001 - errors cross the pipe as data
            res = {"ok": False, "error": f"{type(e).__name__}: {e}"}
        print(json.dumps(res), flush=True)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--backend", default="mlx", choices=("mlx", "echo"))
    args = ap.parse_args()
    try:
        backend = MlxBackend() if args.backend == "mlx" else EchoBackend()
    except Exception as e:  # noqa: BLE001
        print(json.dumps({"ok": False, "error": f"backend unavailable: {type(e).__name__}: {e}"}), flush=True)
        return
    serve(backend)


if __name__ == "__main__":
    main()
