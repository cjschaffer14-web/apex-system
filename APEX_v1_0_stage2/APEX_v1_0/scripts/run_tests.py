#!/usr/bin/env python3
"""Run the whole v1.0 test suite and fail on any test failure OR any ResourceWarning (e.g. an unclosed SQLite
connection), not only on assertion errors.

    python3 scripts/run_tests.py                 # writes nothing; prints the verbose unittest log
    python3 scripts/run_tests.py --out stage1a/test_output.txt
"""
from __future__ import annotations

import argparse
import gc
import io
import os
import platform
import sqlite3
import sys
import time
import unittest
import warnings
from pathlib import Path

sys.dont_write_bytecode = True
os.environ["PYTHONDONTWRITEBYTECODE"] = "1"
ROOT = Path(__file__).resolve().parents[1]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=None)
    ap.add_argument("--pattern", default="test_*.py")
    a = ap.parse_args()
    caught: list[str] = []
    original = warnings.showwarning

    def record(message, category, filename, lineno, file=None, line=None):
        if issubclass(category, ResourceWarning):
            caught.append(f"{filename}:{lineno}: {message}")
        original(message, category, filename, lineno, file, line)

    warnings.simplefilter("always", ResourceWarning)
    warnings.showwarning = record
    buf = io.StringIO()
    stream = _Tee(sys.stderr, buf)
    header = [f"# APEX v1.0 test run - {time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime())}",
              f"# python {sys.version.split()[0]} | sqlite {sqlite3.sqlite_version} | {platform.platform()}"]
    try:
        import numpy, pandas, scipy, sklearn          # noqa: E401
        header[-1] += (f" | numpy {numpy.__version__} | pandas {pandas.__version__} | scipy {scipy.__version__}"
                       f" | scikit-learn {sklearn.__version__}")
    except ImportError as e:
        header.append(f"# missing package: {e}")
    header.append(f"# command: python3 scripts/run_tests.py (unittest discover -s tests_v10 -p '{a.pattern}', "
                  "ResourceWarnings counted as failures)")
    stream.write("\n".join(header) + "\n\n")
    suite = unittest.defaultTestLoader.discover(str(ROOT / "tests_v10"), pattern=a.pattern, top_level_dir=str(ROOT / "tests_v10"))
    result = unittest.TextTestRunner(stream=stream, verbosity=2, warnings=None).run(suite)
    gc.collect()                                   # surface warnings from objects collected after the last test
    stream.write(f"\nResourceWarnings: {len(caught)}\n")
    for c in caught:
        stream.write(f"  {c}\n")
    ok = result.wasSuccessful() and not caught
    stream.write(f"RESULT: {'PASS' if ok else 'FAIL'} ({result.testsRun} tests, {len(result.failures)} failures, "
                 f"{len(result.errors)} errors, {len(result.skipped)} skipped, {len(caught)} ResourceWarnings)\n")
    if a.out:
        (ROOT / a.out).parent.mkdir(parents=True, exist_ok=True)
        (ROOT / a.out).write_text(buf.getvalue())
    return 0 if ok else 1


class _Tee(io.TextIOBase):
    def __init__(self, *streams):
        self.streams = streams

    def write(self, s):
        for st in self.streams:
            st.write(s)
        return len(s)

    def flush(self):
        for st in self.streams:
            st.flush()


if __name__ == "__main__":
    sys.exit(main())
