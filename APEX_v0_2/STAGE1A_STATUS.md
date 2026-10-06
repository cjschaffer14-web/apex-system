# APEX v1.0: Stage 1A status (checkpoint, NOT complete)

**Purpose.** This is a handoff checkpoint written when the owner's session limit reached 90%. Stage 1A is **in progress**. Do not review it as a finished stage, and do not start Stage 2.

**Instruction being implemented:** the Stage 1 review ("Stage 1 approved, subject to a short Stage 1A evidence-closure pass", items 1–6).

## Fixed points, which are unchanged

- **Accepted Stage 1 snapshot.** `stage1/STAGE1_MANIFEST.json` (sha256 `a4591d7e7e501232c50658b0019061b7029d74b56bd40a5fec614f616749f8ee`) lists all 642 Stage 1 files.
  - Every Stage 1 evidence file is byte-identical to that manifest.
  - Only two test files changed (item 5 below). Running `stage1/STAGE1_MANIFEST.json` checks shows only those two differences.
- **Stage 1 hashes.**
  - Database file `2b5f420c…`.
  - Database logical `b6be7251…`.
  - Ledger `70661932…`.
- **Stage 1 code.** `apex_v10/interfaces.py` and everything under `apex_v10/data/` are untouched, so `scripts/build_stage1.py` still reproduces the accepted Stage 1 hashes.
- **Add-only rule.** Every Stage 1A change lives in new files.

## Done and verified

**Item 5 (ResourceWarnings): done.**
- Every SQLite connection in `tests_v10/test_stage1_pit_coverage.py` and `tests_v10/test_stage1_sources.py` is now closed.
- `scripts/run_tests.py` runs the whole suite. It fails on any test failure **or any ResourceWarning**; a deliberately leaked connection was correctly flagged.
- Checkpoint run: 68 tests pass, 0 ResourceWarnings (`stage1a/test_output_checkpoint.txt`).

**Item 1 (types): done.** `apex_v10/interfaces_1a.py`:
- `ValueVintageQuality` takes the values `first_release`, `unrevised_since_release`, `market_record`, `latest_vintage`, `edited_after_release` and `unverified`.
- `EVIDENCE_VINTAGES` is {`first_release`, `unrevised_since_release`, `market_record`}.
- `EVIDENCE_TIMING` is every timing quality except `approximate`.
- `is_evidence_grade(time, vintage)` requires both.
- `Observation1A` and `Feature1A` carry `value_vintage_quality` separately from `availability_quality`, which is exposed as `availability_time_quality`.

**Item 2 (types): done.**
- `TrialRecord1A` extends `TrialRecord` with `selection_family_id`, `objective_metric`, `comparable_set_id`, `investable` and `reproduction`.
- `identity_sha256()` is inherited unchanged, so each 1A record maps to exactly one Stage 1 record.
- A CSCV column must be investable, not a hypothesis test, stored, and per-period (daily, weekly or hourly).
- The module also defines the `SelectionFamily` and `ComparableSet` types.

**Item 1 (data): H.4.1 first-release recovery from the Board's archived release documents.**
- Adapter: `apex_v10/data/sources/h41_releases.py`.
- 666 archived release pages fetched into `data_v10/raw_1a/` (deterministic gzip plus `MANIFEST.jsonl`, about 16 MB).
- **651 of 666 Wednesdays recovered.** Audit file: `data_v10/raw_1a/H41_FETCH_AUDIT.json`.
- The other 15 failed the parser's header-date check ("table names another Wednesday"). Those pages place an extra date, such as the release date or a footnote date, in the table header. **To do:** take the Wednesday from the "Wednesday <date>" column label, rather than the first date in the header.
- Sample cross-check: the 2026-09-23 value of 6,747,704 (millions of USD) equals the Stage 1 DDP value.

**Item 4 (forensic inputs): archived.**
- Location: `data_v10/imports/apex_v05/forensic/` (`FORENSIC_INPUTS.json` holds the SHA-256 of every original byte stream). Contents:
  - the 20 Coinbase JSON files the 2 Oct scripts read;
  - the media data cache;
  - the six-cycle script and its output;
  - the run logs;
  - the two complete code trees that ran (v0.5 run and v0.5.1 run).
- `derived/v05_store_digest.json` proves the v0.5 store's `candles` table is identical to the frozen database's. The v0.5 research reads only candles.
- Importer: `scripts/import_forensic_inputs.py`. It is one-off and refuses to overwrite the archive. No key files were copied; the runs' `state/` folders were excluded.

**Item 4 (forensic harness): done.** `apex_v10/forensics/harness.py`:
- Archived scripts run unmodified, from hash-checked bytes, in a sandbox.
- `apex` imports are bound to the archived code tree.
- Observation is passive: line probes that copy local variables, and pass-through wrappers.

**Item 4 (reproductions): run and verified for the 30 ad hoc trials of 2 Oct 2026.** Rerun with `apex_v10/forensics/runs.adhoc_2026_10_02`, about 3 minutes.
- **22 return series recovered.** Every archived metric reproduces exactly, and the captured path gives the same metric through the script's own function:
  - walk-forward: 9;
  - Fibonacci named-ratio and thirds paths: 8;
  - cross-sectional books: 5.
- **5 reproduced as statistics only**, because they have no single return path: the 4 random-level placebo aggregates and the six-cycle check.
- **3 mismatches, which stay unavailable:** ETH hourly walk-forward at 80, 40 and 5 bps.
  - Every archived number that exists reproduces exactly.
  - But the archived entries lack three fields that the archived `baseline.py` always writes. So they came from an earlier, unarchived script version, and the original definition cannot be proven.
- Noted: the Fibonacci key says "45bps", but the script charges 40 bps. The stored path is the 40 bps path the script computed.

## Not done yet

1. **Item 4, remaining reproductions.** Code is written in `apex_v10/forensics/runs.py` but not yet run:
   - owner ideas of 3 Oct (82 trials: levels, Occam, Occam check, media, media vol partial);
   - governed v0.5 (14 research books plus 7 hypotheses);
   - v0.5.1 (15 hypotheses).

   Expected recoverable paths: 18 Occam, 3 Occam-check ETH, 14 v0.5 weekly books, 2 v0.5.1 rules. All the others are statistics only.
2. **Item 1, Stage 1A database.** Planned design:
   - Copy the Stage 1 database (verify `2b5f420c` / `b6be7251`) to `data_v10/market_2026-10-03_v10_1a.sqlite`, with schema `1.0.1-stage1a` and its own manifest.
   - Add a `value_vintage_quality` column to `macro_observations` and `funding_events`, plus a virtual `availability_time_quality` alias.
   - Add a `vintage_policy` table and a `macro_revisions` table (first print, second print and DDP latest, for H.4.1).
   - Insert the first-release rows under a new family, `macro:fed_h41_first_release:RESPPMA_N.WW`.

   Planned classification:

   | Data | Vintage quality | Evidence-grade? |
   |---|---|---|
   | H.4.1 DDP rows | `latest_vintage` | No |
   | H.4.1 recovered rows | `first_release` | Yes |
   | NY Fed RRP, same-day stamp | `unrevised_since_release` | Yes |
   | NY Fed RRP, edited later (497 rows) | `edited_after_release` | No |
   | TGA | `unverified` | No (the DTS document archive host is unreachable from this environment) |
   | Treasury par yields, VIX, funding events, candles | `market_record` | Yes, by source practice; **reviewer to confirm** |
   | Coin Metrics | `latest_vintage` | No |
   | Other legacy readings | `unverified` | No |
3. **Evidence-grade gate.** Planned as `apex_v10/data/gate_1a.py`: Stage 1 `coverage.evaluate` applied to a stricter family predicate, where rows that are not evidence-grade count as missing. It needs `require(..., grade="evidence")` and the matching point-in-time lookups.
4. **Items 2 and 3.**
   - Ledger v1a, as a new file: one record per Stage 1 record, with the selection fields and the forensic outcomes.
   - Selection families by research batch, cost level and objective. Where one record summarises several evaluations (for example, 40 random-level placebos in one record), family N counts the alternatives evaluated.
   - A DSR input table: global N = 1,483, family N, T, skew and kurtosis. No DSR verdicts.
   - CSCV matrices only for investable, aligned series within one comparable set, with identical columns collapsed by `return_equivalence_id`. Geometry cells, conditional cells, state-forward rows and hypothesis tests are excluded.
5. **Tests** for all of the above; a clean-room rebuild; `STAGE1A_REPORT.md`.
6. **Item 6, packaging.** One consolidated full-project ZIP with a single canonical root. This checkpoint ZIP already uses that layout.

## How to continue (any implementer)

```
cd APEX_v1_0
python3 scripts/run_tests.py                 # must stay green, with 0 ResourceWarnings
python3 -c "import sys; sys.path.insert(0,'.'); from pathlib import Path; from apex_v10.forensics.harness import Inputs; \
from apex_v10.forensics import runs as R; import hashlib; root=Path('.'); \
sha={p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in (root/'data_v10/imports/apex_v05/research_2026-10-02').glob('*.py')}; \
[print(o.status, o.trial_id) for o in R.adhoc_2026_10_02(root, Inputs(root), sha)]"
```

The Stage 1 database is not in this checkpoint ZIP. Either rebuild it with `python3 scripts/build_stage1.py` (about 80 s, from `data_v10/raw`), or decompress the delivered `APEX_v1_0_stage1_db.sqlite.gz` to `data_v10/market_2026-10-03_v10.sqlite`.

**Rules to keep:**
- Add-only.
- Never edit Stage 1 files.
- No tuning; a path counts only if its metrics reconcile exactly.
- Every new artifact carries a version, a SHA-256, provenance and its parent hash.
- Stop after Stage 1A for review.
