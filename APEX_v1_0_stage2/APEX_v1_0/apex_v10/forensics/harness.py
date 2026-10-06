"""Run archived research scripts UNMODIFIED in an isolated sandbox and observe them.

What "frozen forensic reproduction" means here:
  * the script's source bytes are the archived bytes (hash-checked against FORENSIC_INPUTS.json) and are compiled
    as-is; nothing in them is edited, patched or re-parameterised;
  * its imports resolve to the archived code tree of the original run (an `apex` package built from
    code/<run>/apex), never to whatever happens to be installed;
  * its inputs are the archived original inputs, placed where the script expects them (its working directory);
  * observation is passive: a line probe copies local variables when execution reaches a named line, or a
    pass-through wrapper records what a library function returned. Neither changes a value the script computes.
"""
from __future__ import annotations

import contextlib
import copy
import gzip
import hashlib
import importlib
import json
import os
import shutil
import sys
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Iterator, Optional

FORENSIC_REL = "data_v10/imports/apex_v05/forensic"
IMPORTS_REL = "data_v10/imports/apex_v05"


class ForensicInputError(RuntimeError):
    pass


def _sha(b: bytes) -> str:
    return hashlib.sha256(b).hexdigest()


class Inputs:
    """The archived originals, verified against FORENSIC_INPUTS.json on every read."""

    def __init__(self, root: Path) -> None:
        self.root = Path(root)
        self.base = self.root / FORENSIC_REL
        man = json.loads((self.base / "FORENSIC_INPUTS.json").read_text())
        self.index = {f["path"]: f for f in man["files"]}

    def read(self, rel: str) -> bytes:
        f = self.index.get(rel)
        if f is None:
            raise ForensicInputError(f"not an archived forensic input: {rel}")
        raw = (self.base / rel).read_bytes()
        body = gzip.decompress(raw) if f["gzip"] else raw
        if _sha(body) != f["sha256"]:
            raise ForensicInputError(f"archived input {rel} does not match its recorded SHA-256")
        return body

    def code_tree(self, run: str) -> list[str]:
        prefix = f"code/{run}/apex/"
        return sorted(p for p in self.index if p.startswith(prefix))

    def sha(self, rel: str) -> str:
        return self.index[rel]["sha256"]


def script_bytes(root: Path, rel: str, expected_sha: Optional[str] = None) -> bytes:
    """An archived script from data_v10/imports/apex_v05 (Stage 1 import) or the forensic archive."""
    p = Path(root) / IMPORTS_REL / rel
    body = p.read_bytes()
    if expected_sha and _sha(body) != expected_sha:
        raise ForensicInputError(f"{rel} changed since it was archived")
    return body


# ---------------------------------------------------------------------------------------------------------------
# observation
# ---------------------------------------------------------------------------------------------------------------
@dataclass
class LineProbe:
    """Call `capture(frame)` each time execution in function `func` of `filename` reaches the line whose source
    contains `marker` (the marker must occur exactly once in the file). The frame is only read."""
    filename: str
    func: str
    marker: str
    capture: Callable[[Any], None]
    lineno: int = 0

    def resolve(self, source: str) -> None:
        hits = [i for i, line in enumerate(source.splitlines(), start=1) if self.marker in line]
        if len(hits) != 1:
            raise ForensicInputError(f"probe marker {self.marker!r} found {len(hits)} times in {self.filename}")
        self.lineno = hits[0]


@contextlib.contextmanager
def probes(active: list[LineProbe]) -> Iterator[None]:
    table: dict[tuple[str, str], dict[int, list[LineProbe]]] = {}
    for p in active:
        table.setdefault((p.filename, p.func), {}).setdefault(p.lineno, []).append(p)

    def local(frame, event, arg):
        if event == "line":
            for p in table[(frame.f_code.co_filename, frame.f_code.co_name)].get(frame.f_lineno, ()):
                p.capture(frame)
        return local

    def glob(frame, event, arg):
        if event == "call" and (frame.f_code.co_filename, frame.f_code.co_name) in table:
            return local
        return None

    previous = sys.gettrace()
    sys.settrace(glob)
    try:
        yield
    finally:
        sys.settrace(previous)


@contextlib.contextmanager
def recording(module: Any, attr: str, record: Callable[[tuple, dict, Any, Any], None]) -> Iterator[None]:
    """Pass-through wrapper: the original function runs with the original arguments and its result is returned
    unchanged; `record(args, kwargs, result, caller_frame)` only observes."""
    original = getattr(module, attr)

    def wrapper(*args, **kwargs):
        out = original(*args, **kwargs)
        record(args, kwargs, out, sys._getframe(1))
        return out

    setattr(module, attr, wrapper)
    try:
        yield
    finally:
        setattr(module, attr, original)


def snapshot(frame, names: tuple[str, ...]) -> dict:
    loc = frame.f_locals
    return {n: copy.deepcopy(loc[n]) for n in names if n in loc}


# ---------------------------------------------------------------------------------------------------------------
# sandbox
# ---------------------------------------------------------------------------------------------------------------
class Sandbox:
    """A temporary working directory holding the archived scripts and inputs, plus an `apex` package built from an
    archived code tree. While active, `apex` and the scripts' own module names resolve only inside the sandbox."""

    def __init__(self, inputs: Inputs, code_run: Optional[str]) -> None:
        self.inputs, self.code_run = inputs, code_run
        self.tmp: Optional[tempfile.TemporaryDirectory] = None
        self.work = self.pkg = Path()
        self._saved: dict[str, Any] = {}
        self._names: set[str] = set()

    def __enter__(self) -> "Sandbox":
        self.tmp = tempfile.TemporaryDirectory(prefix="apex_forensic_")
        base = Path(self.tmp.name)
        self.work, self.pkg = base / "work", base / "pkg"
        self.work.mkdir()
        self.pkg.mkdir()
        if self.code_run:
            prefix = f"code/{self.code_run}/"
            for rel in self.inputs.code_tree(self.code_run):
                out = self.pkg / rel[len(prefix):]
                out.parent.mkdir(parents=True, exist_ok=True)
                out.write_bytes(self.inputs.read(rel))
        self._saved = {"cwd": os.getcwd(), "path": list(sys.path), "argv": list(sys.argv),
                       "dont_write_bytecode": sys.dont_write_bytecode}
        self._purge()
        sys.dont_write_bytecode = True
        sys.path[:0] = [str(self.pkg), str(self.work)]
        os.chdir(self.work)
        if self.code_run:                                  # bind `apex` to the archived tree before any script runs
            importlib.import_module("apex")
            importlib.import_module("apex.ext")
            if Path(sys.modules["apex"].__file__).resolve().parent != (self.pkg / "apex").resolve():
                raise ForensicInputError("`apex` did not resolve to the archived code tree")
        return self

    def __exit__(self, *exc) -> None:
        os.chdir(self._saved["cwd"])
        sys.path[:] = self._saved["path"]
        sys.argv[:] = self._saved["argv"]
        sys.dont_write_bytecode = self._saved["dont_write_bytecode"]
        self._purge()
        if self.tmp:
            self.tmp.cleanup()

    def _purge(self) -> None:
        for name in list(sys.modules):
            if name == "apex" or name.startswith("apex.") or name in self._names:
                del sys.modules[name]

    def place(self, name: str, body: bytes) -> Path:
        p = self.work / name
        p.write_bytes(body)
        if name.endswith(".py"):
            self._names.add(name[:-3])
        return p

    def module(self, dotted: str):
        return importlib.import_module(dotted)

    def run_script(self, name: str, argv: tuple[str, ...] = (), probe_list: tuple[LineProbe, ...] = (),
                   as_main: bool = True, call: Optional[str] = None, call_args: tuple = ()) -> dict:
        """Compile and execute the placed script with its own path as filename. With `as_main=False` the module
        body runs without the `__main__` block and `call` (e.g. "main") is invoked afterwards."""
        path = self.work / name
        source = path.read_text()
        for p in probe_list:
            p.filename = str(path)
            p.resolve(source)
        code = compile(source, str(path), "exec")
        g: dict[str, Any] = {"__name__": "__main__" if as_main else name[:-3], "__file__": str(path),
                             "__builtins__": __builtins__}
        sys.argv[:] = [str(path), *argv]
        with probes(list(probe_list)):
            exec(code, g)
            if call:
                g[call](*call_args)
        if not as_main:
            sys.modules[name[:-3]] = type(sys)(name[:-3])
            sys.modules[name[:-3]].__dict__.update(g)
        return g

    def read_json(self, name: str) -> Any:
        return json.loads((self.work / name).read_text())
