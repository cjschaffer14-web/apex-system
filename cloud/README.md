# APEX cloud components

Source pulled on 2026-11-14 from Google Cloud project `alert-maker-509913-m7`
(region `us-central1`). Each folder is the most recent source archive that was
uploaded for that component's build; nothing here was edited after download
(only `__pycache__` was dropped).

| Folder | Runs as | Trigger | Source archive |
| --- | --- | --- | --- |
| `apex-stream/` | VM `apex-stream-v1` (container `apex-public/stream`) | always on; see `vm-startup-script.sh` | Cloud Build `stream:realtime-triangles-v6`, 2026-10-07 |
| `apex-public-collector/` | Cloud Run jobs `apex-public-collect`, `apex-public-monitor` | scheduler: every 20 min / hourly at :07 | Cloud Build `collector:v1`, 2026-10-07 |
| `apex-microcap-collect/` | Cloud Run job `apex-microcap-collect` | scheduler: every 20 min | Cloud Build `microcap:v1`, 2026-10-07 |
| `apex-cloud-auditor/` | Cloud Run job `apex-cloud-auditor` | scheduler `apex-daily-audit`: 04:00 daily | run-sources upload, 2026-10-11 |
| `apex-dex-paper-intake/` | Cloud Run service `apex-dex-paper-intake` | scheduler: every minute | run-sources upload, 2026-10-25 |
| `apex-paper-pilot/` | Cloud Run service `apex-paper-pilot`, job `apex-paper-pilot-smoke` | on request | Cloud Build `paper-pilot:broker-ledger-20261103-v2`, 2026-11-03 |
| `apex-freqtrade/` | Cloud Run job `apex-freqtrade` | manual | Cloud Build `apex-freqtrade:latest`, 2026-10-30 |
| `apex-calendar-push/` | Cloud Run service `apex-calendar-push` | on request | run-sources upload, 2026-11-04 |
| `runtime-apex-external-canary/` | image `schaffer-workspace/runtime:apex-external-canary-20261104` | n/a | Cloud Build, 2026-11-04 |

## Caveats

- The deployed image for a component can be newer or older than the archive
  here: the `apex-paper-pilot` service and the `apex-stream` VM are pinned to
  image digests, and the digest-to-archive match was inferred from build
  order, not verified.
- `apex-freqtrade` builds on a `freqtrade-base:develop` image whose 50 MB
  source archive (upstream freqtrade) is not included.
- API keys are not in this tree. `apex-cloud-auditor` reads its keys from
  Secret Manager (`dec-openai-api-key`, `dec-anthropic-api-key`,
  `dec-gemini-api-key`); see `apex-cloud-auditor/finish.sh`.
- Data buckets (`*-apex-public-v1`, `*-apex-public-stream-v2`,
  `*-apex-paper-pilot`, `*-apex-dex-paper-intake`) are not included.
- Non-APEX services in the same project (`dec-*`, `gemini-*`, `schaffer-*`,
  `portal`, `ai10k-collector-job`) are not included.
