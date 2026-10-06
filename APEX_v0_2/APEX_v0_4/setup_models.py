"""Install APEX's local models on this Mac, once. (v0.4.1)

    python3 setup_models.py            # model environment + every model that fits this Mac's memory
    python3 setup_models.py --fast-only
    python3 setup_models.py --dry-run  # show the plan; change nothing

What it does, in order:
  1. Checks: Apple silicon, native (not Rosetta) Python 3.10+, memory, free disk.
  2. Creates a separate model environment, .venv/, and installs the pinned mlx-vlm into it. APEX itself
     stays standard-library only and never imports MLX; models run in their own worker process.
  3. Downloads each model at a pinned Hugging Face commit into models/<role>/, and verifies every file
     against the hash that commit publishes (SHA-256 for weights, git blob id for small files). Interrupted
     downloads resume.
  4. Pins the verified files in config/model_pins.json. APEX loads nothing that does not match its pin.
  5. Smoke test: loads the fast model and asks it for one word.

Afterwards, `python3 awaken_v04.py` uses the models by itself: the fast model while you work, the deep
model only when the Mac is idle. Network use here is setup only (pypi.org, huggingface.co), started by you.
"""
from __future__ import annotations
import argparse, json, shutil, subprocess, sys, time, urllib.request
from pathlib import Path

HOME = Path(__file__).resolve().parent
sys.path.insert(0, str(HOME))
from apex.ext.local_models import (CATALOG, MLX_VLM_VERSION, model_dir, roles_for_ram, apple_silicon, ram_gb,  # noqa: E402
                                   verify_file, folder_digest)

HF = "https://huggingface.co"
SKIP = {".gitattributes"}


def say(msg: str) -> None:
    print(msg, flush=True)


def get_json(url: str) -> dict:
    req = urllib.request.Request(url, headers={"User-Agent": "APEX-setup/0.4.1"})
    with urllib.request.urlopen(req, timeout=60) as r:
        return json.loads(r.read().decode())


def download(url: str, dest: Path, size: int) -> None:
    part = dest.with_name(dest.name + ".part")
    have = part.stat().st_size if part.exists() else 0
    headers = {"User-Agent": "APEX-setup/0.4.1"}
    if have:
        headers["Range"] = f"bytes={have}-"
    req = urllib.request.Request(url, headers=headers)
    with urllib.request.urlopen(req, timeout=120) as r:
        if have and r.status != 206:
            have = 0                                   # server ignored the range: start over
        mode = "ab" if have else "wb"
        done, last, t0 = have, 0.0, time.time()
        with part.open(mode) as f:
            for chunk in iter(lambda: r.read(8 << 20), b""):
                f.write(chunk)
                done += len(chunk)
                if size > 50 << 20 and time.time() - last > 5:
                    rate = (done - have) / max(1e-6, time.time() - t0) / 2 ** 20
                    say(f"      {dest.name}: {done / 2 ** 30:.2f} / {size / 2 ** 30:.2f} GB ({rate:.0f} MB/s)")
                    last = time.time()
    part.replace(dest)


def fetch_model(role: str) -> dict:
    spec = CATALOG[role]
    meta = get_json(f"{HF}/api/models/{spec['repo']}/revision/{spec['revision']}?blobs=true")
    if meta.get("sha") != spec["revision"]:
        raise SystemExit(f"{spec['repo']}: Hugging Face returned commit {meta.get('sha')}, expected {spec['revision']}")
    target = model_dir(HOME, role)
    target.mkdir(parents=True, exist_ok=True)
    files: dict[str, str] = {}
    for sib in meta["siblings"]:
        name = sib["rfilename"]
        if name in SKIP or "/" in name:
            continue
        dest = target / name
        ok, why, sha = verify_file(dest, sib)
        if not ok:
            say(f"    downloading {name} ({int(sib.get('size', 0)) / 2 ** 20:.0f} MB)")
            download(f"{HF}/{spec['repo']}/resolve/{spec['revision']}/{name}", dest, int(sib.get("size", 0)))
            ok, why, sha = verify_file(dest, sib)
        if not ok:
            dest.unlink(missing_ok=True)
            raise SystemExit(f"{name}: verification failed ({why}); the file was removed. Run setup again.")
        files[name] = sha
        say(f"    ok  {name}  ({why})")
    return {"name": spec["repo"], "role": role, "kind": spec["kind"], "license": spec["license"],
            "path": str(target.relative_to(HOME)), "source": f"{HF}/{spec['repo']}/tree/{spec['revision']}",
            "revision": spec["revision"], "files": files, "sha256": folder_digest(files),
            "verified_on": time.strftime("%Y-%m-%d")}


def write_pins(artifacts: list[dict]) -> Path:
    pins = HOME / "config" / "model_pins.json"
    old = json.loads(pins.read_text()).get("artifacts", []) if pins.exists() else []
    roles = {a["role"] for a in artifacts}
    keep = [a for a in old if a.get("role") not in roles]
    pins.write_text(json.dumps({"note": "Written by setup_models.py. Every file is pinned by SHA-256 after it "
                                        "matched the hash its Hugging Face commit publishes.",
                                "artifacts": keep + artifacts}, indent=1))
    return pins


def main() -> None:
    ap = argparse.ArgumentParser(description="Install APEX's local models")
    ap.add_argument("--fast-only", action="store_true")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--skip-install", action="store_true", help="reuse the existing .venv as is")
    args = ap.parse_args()

    if not apple_silicon():
        raise SystemExit("Local models need a Mac with Apple silicon and a native arm64 Python "
                         "(this Python reports a different platform; Rosetta Pythons report x86_64).")
    if sys.version_info < (3, 10):
        raise SystemExit(f"Python 3.10 or newer is needed (this is {sys.version.split()[0]}). "
                         "Install one from python.org or Homebrew, then run this again with it.")
    mem = ram_gb()
    roles = ["fast"] if args.fast_only else roles_for_ram(mem)
    if not roles:
        raise SystemExit(f"This Mac has {mem:.0f} GB of memory; the smallest model needs 16 GB.")
    need = sum(CATALOG[r]["size_gb"] for r in roles) + 1.5
    free = shutil.disk_usage(HOME).free / 2 ** 30
    say(f"Mac: Apple silicon, {mem:.0f} GB memory, {free:.0f} GB free disk")
    for r in roles:
        c = CATALOG[r]
        say(f"  {r:4s}  {c['repo']} @ {c['revision'][:10]}  ~{c['size_gb']} GB  used in: {', '.join(c['bands'])}")
    say(f"  model environment: .venv with mlx-vlm=={MLX_VLM_VERSION}   total disk needed: ~{need:.0f} GB")
    if free < need:
        raise SystemExit(f"Not enough free disk: {free:.0f} GB free, about {need:.0f} GB needed.")
    if args.dry_run:
        return

    venv_py = HOME / ".venv" / "bin" / "python"
    if not args.skip_install:
        if not venv_py.exists():
            say("Creating the model environment (.venv) ...")
            subprocess.run([sys.executable, "-m", "venv", str(HOME / ".venv")], check=True)
        say(f"Installing mlx-vlm=={MLX_VLM_VERSION} into .venv ...")
        subprocess.run([str(venv_py), "-m", "pip", "install", "--quiet", "--upgrade", "pip"], check=True)
        subprocess.run([str(venv_py), "-m", "pip", "install", "--quiet", f"mlx-vlm=={MLX_VLM_VERSION}"], check=True)

    artifacts = []
    for r in roles:
        say(f"Model '{r}': {CATALOG[r]['repo']}")
        artifacts.append(fetch_model(r))
    pins = write_pins(artifacts)
    say(f"Pinned {len(artifacts)} model(s) in {pins.relative_to(HOME)}")

    say("Smoke test: loading the fast model ...")
    from apex.ext.local_models import WorkerClient
    w = WorkerClient([str(venv_py), "-m", "apex.ext.model_worker", "--backend", "mlx"], HOME)
    try:
        hello = w.call({"op": "ping"}, timeout=180)
        if not hello.get("ok"):
            raise SystemExit(f"Model worker could not start: {hello.get('error')}")
        say(f"  runtime: {hello.get('versions')}")
        res = w.call({"op": "load", "path": str(model_dir(HOME, 'fast'))}, timeout=600)
        if not res.get("ok"):
            raise SystemExit(f"Could not load the fast model: {res.get('error')}")
        out = w.call({"op": "generate", "prompt": "Reply with exactly one word: ready", "images": [],
                      "max_tokens": 64}, timeout=600)
        if not out.get("ok"):
            raise SystemExit(f"Generation failed: {out.get('error')}")
        from apex.ext.local_models import THINK
        say(f"  fast model says: {THINK.sub('', out.get('text', '')).strip()[:80]!r}  ({out.get('tps', 0):.0f} tokens/s)")
    finally:
        w.close()
    say("Done. Start APEX with: python3 awaken_v04.py")


if __name__ == "__main__":
    main()
