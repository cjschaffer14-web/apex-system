# Apex broker reconciliation 1.3

Profit path: capture independently auditable paper-broker balances and prevent
capital deposits, missing fees, or unrelated model books from becoming a profit claim.

This package supports read-only Alpaca **paper** account `PA3YUD5NA`. It never
places/cancels orders, enables trading, changes IAM, provisions credentials,
or changes a frozen virtual experiment. There are no timers or start actions.
The parent owns installation through pkgctl. It installs no new dependencies.

## Reconstructed broker ledger

`broker_ledger.py` independently rebuilds USD cash and FIFO asset quantities from
the observed October 22 preflight opening balance and all retained broker events.
It never initializes shadow cash or quantities from today's broker balances.
Opening cash 1,000,000 USD is an actual historical preflight observation at
20:29:10 UTC, independently confirmed by the only pre-baseline activity: an earlier
1,000,000 USD cash journal funding entry. Full retained history starts before
account creation at 19:47 UTC; any earlier security movement, unknown activity,
missing coverage, duplicate conflict or inconsistent opening funding refuses.

The saved November 3 lifecycle evidence contains 1,253 order records and 2,489
activities: 1,244 fills, 1,244 crypto fee postings and the opening funding journal.
Every fill's order ID/side/symbol and the sum of its order's fill quantities are
checked against independently read order records, including partial fills on
canceled orders. Replaying posted cash and fee-asset quantities reconstructs
cash/equity 999,968.00 USD and exactly zero BTC/ETH/SOL, matching observed broker
cash/equity 999,968 and flat positions with zero residual. The independent October
22 post-loop cash/flat checkpoint 999,999.94 also matches. This is paper-broker
ledger reconciliation; the account's change after capital flows is -32.00 USD,
not verified strategy profit and not actual live execution.

The cash posting policy is pinned to [Alpaca's provider reply on transaction
rounding](https://forum.alpaca.markets/t/does-alpaca-rounds-up-or-down-to-the-nearest-penny-when-dealing-with-account-balances/17303)
by Dan_Whitnable_Alpaca, August 7, 2025: non-regulatory USD transactions use nearest
cent, HALF_EVEN. Applying that general rule to each crypto-paper fill is an explicit
interpretation, corroborated by the separate historical broker checkpoint and
current retained full-account reconstruction. It is not represented as a quoted
crypto-paper settlement specification. Posted cash fees (16.12 USD) and base-asset
fee quantities are used exactly as returned, without applying another fee rate or
deducting base-asset fees from cash a second time. The exact unrounded notional
diagnostic is retained: cash 999,968.637055291698323484, a +0.637055291698323484 USD
residual. That difference is the disclosed posting-precision adjustment, not an
unexplained plug or widened reconciliation tolerance. Tie-to-even cases and low
ambient Decimal precision are tested explicitly.

Some fee postings appear days after the associated execution, and most fee rows
lack order IDs. Complete retained posted-fee parsing does not establish per-order
fee attribution, actual live costs or protection from future provider revisions.
FIFO base-fee basis is consumed at the recorded posting time and is not offered as
unique per-strategy attribution. Non-flat reconstructed equity is withheld until
independent contemporaneous valuation marks are supplied; current broker position
market values are never copied into shadow equity.

Canonical private source archives live in
`~/SchafferAI-data/financial-evidence/source-bundles/<SHA256>.json`, preserving exact
input bytes. Immutable reports and `latest-ledger.json` live in the chosen records
directory. Pointer writes are locked, atomic, read back and refuse older capture
times. Schema `apex_broker_ledger_report/1` contains a bounded `display_summary`
with baseline/source hashes, replay boundary, source asof, exact residuals, fee
evidence limits and paper/profitability/order flags for the root's report mirror.
Full private broker records stay in source archives, not the display summary.

Replay the package fixtures without authentication or HTTP:

```
python3 ~/.schafferai/apex-broker-reconciliation/broker_ledger.py \
  --bundle ~/.schafferai/apex-broker-reconciliation/evidence/lifecycle-20261103.json \
  --baseline ~/.schafferai/apex-broker-reconciliation/evidence/opening-baseline.json \
  --checkpoints ~/.schafferai/apex-broker-reconciliation/evidence/checkpoints.json \
  --baseline-source ~/.schafferai/apex-broker-reconciliation/evidence/preflight-source-20261022.json \
  --checkpoint-source ~/.schafferai/apex-broker-reconciliation/evidence/checkpoint-source-20261022.json \
  --archive-sources ~/SchafferAI-data/financial-evidence/source-bundles \
  --output ~/SchafferAI-data/financial-evidence/broker-ledger
```

`broker_lifecycle.py --since-account-creation --until <aware UTC cutoff> --output
<private path>` refreshes the retained history using an explicitly selected auth
mode. Daily windows overlap and exact IDs deduplicate; a 500-order page splits
recursively into smaller overlapping windows rather than asserting completeness.
The cloud extension adds IAM-protected GET `/api/broker-lifecycle` with the same
required after/until parameters, 24-hour and URL limits and account gates as the
snapshot route. It returns full positions, activities, order records and account
creation metadata. Cloud requests need no new credential/IAM role. The parent
owns deploying that extension and any scheduled refresh; this package has no new
cloud schedule or order route.

`broker_bundle.py` provides the canonical offline assembler for recorded daily
receipts. Its pure `assemble(list_of_exact_json_bytes)` function has no network or
filesystem access. It validates paper account/UUID/currency/creation identity,
complete daily bounds and capture durations, exact-ID equality, overlap without
coverage gaps starting at account creation, and a final broker observation no more
than 120 seconds after the replay cutoff. Conflicting duplicate activity/order
IDs or conflicting same-time final balances refuse. Identical receipts and records
deduplicate deterministically; source receipt hashes and the selected observation
hash remain in provenance. The CLI adds its own code hash and verifies immutable
bundle readback. It never replaces or rewrites existing archived bundles.

```
python3 ~/.schafferai/apex-broker-reconciliation/broker_bundle.py \
  --windows-dir /path/to/recorded-daily-windows \
  --output ~/SchafferAI-data/financial-evidence/source-bundles
```

`--window /path/to/receipt.json` may be repeated for explicit inputs. Directory
mode ignores JSON files bearing other schemas (for example collection indexes),
reports their count, and refuses malformed JSON. The output acknowledgement names
the new content-addressed bundle; pass it to `broker_ledger.py` with the preserved
baseline/checkpoint archives. The original archived 528dc15f… bundle and its ledger
remain replayable unchanged. Packaging version 1.3 adds this offline assembler;
collector and ledger code versions/hashes from 1.2 are deliberately unchanged.

## Existing Cloud Run integration

Fresh November 3 metadata confirms existing `apex-paper-pilot` already runs as
`apex-paper-pilot@alert-maker-509913-m7.iam.gserviceaccount.com`, with version-1
references for both broker secrets mounted as `APEX_PAPER_KEY` and
`APEX_PAPER_SECRET`. Each secret's resource IAM grants that identity accessor.
Root's authenticated `GET /api/status` at 22:27:44 UTC returned current broker
cash/equity and verified account identity. This is an existing durable server-side
credential path: it does not fetch secrets using the Mac's human Cloud SDK token.
The service's invoker policy admits only `user:c@schafferai.com`; it is not public.
The separate e2-micro currently has no attached identity and is not the chosen path.

`cloud-pilot/app.py` is an additive extension of the exact serving source release
`7719cff72c71253ffcf8c04abd076a0d87fc78b8`, GitHub blob
`e6a09022066ac06d34233c7408573d3fdbf21f38`, adding:

```
GET /api/broker-snapshot?after=<URL-encoded aware timestamp>&until=<URL-encoded aware timestamp>
```

It requires exactly those two nonempty parameters, a URL at most 1024 characters,
and a positive window at most 24 hours ending no later than now. Invalid requests
return 400 before any broker read. The existing configured UUID/excluded-account
gate runs first; the collector independently verifies account number PA3YUD5NA,
USD and ACTIVE status. Only the collector's account/positions/paginated activities
GET allowlist is used. It performs no storage write, order or funding operation.
The response contains `broker_snapshot_version:1`, the base cloud source release,
and SHA256 hashes of the collector and additive app source. Fixed error codes
replace provider exception text. New route execution needs no google-auth import:
it uses existing securely mounted broker credentials inside the attached runtime.

The original POST handler and order-submission method remain unchanged; tests pin
their AST hashes against the serving source. Existing web assets, user, CMD and
other image settings are inherited from the exact currently deployed image digest.
This does not enable/disable existing order routes or change their policy.

The parent owns cloud build/deployment and candidate validation. From this package
root, `cloudbuild.json` runs both fake-transport test suites using the existing base
image, then builds `cloud-pilot/Dockerfile` and pushes to the existing apex-public
repository. It creates no service, identity, bucket, IAM grant or schedule. Default
image substitution is `paper-pilot:broker-ledger-20261103-v2`; timeout is
300 seconds. Deployment must preserve existing IAM, service identity, env/secret
references and scaling, validate a no-traffic candidate's read-only GETs, then
shift traffic only after verified success. This source package by itself is not
proof of deployment or a successful full broker snapshot.

The Mac invocation still authenticates to Cloud Run using its current IAM login.
That caller identity is separate from the server's durable secret access. The
route collects on demand; this change introduces no automatic collection schedule.

## Standalone CLI authentication

The default `--auth-mode workload` uses `google.auth.default` with a Cloud Platform
scope and explicitly accepts only attached metadata credentials or external-account
WIF credentials. It rejects authorized-user ADC, service-account private-key
credentials, and user-sourced impersonation. It refreshes short-lived credentials
and reads only existing Secret Manager references `apex-pilot-paper-key` and
`apex-pilot-paper-secret` in `alert-maker-509913-m7`. Keys stay in memory and error
receipts contain fixed reason codes, never provider exception strings.

The selected Python environment must already contain `google-auth` and its
requests transport dependency. Otherwise it writes `google_auth_dependency_missing`.
Do not install a package or create an account merely to suppress that receipt.

Standalone CLI activation outside the existing mounted-secret Cloud Run route
requires one verified architecture:

- **On Google Cloud:** attach a narrowly privileged service account to the actual
  workload, verify its permission to access these two specific secrets, and run
  the collector inside that workload. Cloud Run metadata cannot be queried from
  the Mac. This Mac package contains reusable code, but does not move the workload.
- **Outside Google Cloud:** establish a supported external OIDC/SAML/X.509/AWS/Azure
  identity, Google workload identity pool/provider and narrow resource/service
  account binding. Provision the official external-account credential configuration
  for that provider using the standard ADC location/environment reference. A Mac
  user refresh token is not a WIF provider. No usable provider was verified here.

Historical `schaffer-worker@alert-maker-509913-m7.iam.gserviceaccount.com`
existence is not proof of present broker-secret permissions. Read current identity
and secret IAM before activation. Do not mint service-account keys or disable
session controls. The verified existing identity is apex-paper-pilot above;
missing local standalone identity/provider setup remains an explicit blocker.

`--auth-mode legacy-manual` is an opt-in diagnostic mode using existing
`~/apex-live/creds.py:alpaca_paper_keys()` unchanged. It can restore one manual
observation after owner provider authentication, but is not unattended auth repair.
The helper can wait up to its existing 120-second gcloud timeout; default workload
mode does not invoke it. Never pass credentials on this CLI or into chat.

## Read-only observation

After installation, with an actual configured workload identity:

```
python3 ~/.schafferai/apex-broker-reconciliation/broker_reconciliation.py \
  --after 2026-11-03T00:00:00Z --until 2026-11-03T12:00:00Z \
  --output ~/.schafferai/apex-broker-reconciliation/records
```

Use a completed activity window ending no later than capture time. The hardcoded
HTTPS host and GET-only endpoint allowlist permit account, positions and activity
reads only. Redirects are refused. Wrong account/currency/inactive-account results
stop before further reads. Activities paginate by the last activity ID with a
100-page limit and duplicate/cycle refusal. Account reads sandwich the capture;
observed balance changes or capture durations over 120 seconds refuse. This is
not an atomic provider snapshot: positions/activity timing and delayed fee postings
remain explicit limits. Activity windows filter creation time; nontrade fee
activities may be created the next UTC day. Reobserve completed windows to capture
late postings rather than silently treating absence as zero fees.

Every response has its raw-byte SHA256 recorded; normalized evidence retains
balances, position quantities/values and accounting activity fields. Credential
headers are never saved. Success and blocked receipts are immutable, content
addressed, mode 0600, and read back byte for byte. Blocked CLI exits 2; successful
snapshot exits 0 unless a requested reconciliation finds a mismatch, which exits 2
and preserves the observed snapshot plus detailed residuals. The CLI acknowledgement
includes `nav_reconciliation`. A snapshot never sets `profitability_verified` true.

## Matched shadow ledger interface

Pass `--shadow path.json` to compare a **separate broker shadow ledger**, using
this schema. Values below are an illustrative test fixture, not observed balances:

```
{
  "schema": "apex_broker_shadow/1", "ledger_kind": "broker_shadow",
  "venue": "alpaca", "mode": "paper", "account_number": "PA3YUD5NA",
  "currency": "USD", "source_sha256": "<64-character source hash>",
  "valuation_window": {
    "started_utc": "<exact broker capture_started_utc>",
    "ended_utc": "<exact broker capture_ended_utc>"
  },
  "cash": "90", "equity": "100",
  "positions": {"XYZ": {"qty": "2", "market_value": "10"}}
}
```

The independent ledger producer must attest and document why its valuation window
matches the captured provider window. Merely copying timestamps does not establish
that evidence. Checks require account/venue/currency/mode and symbol sets to match,
exact quantities, cash/equity/per-position market-value residuals within $0.01,
and cash-plus-position identity on both sides. All residuals remain in the receipt.
This schema intentionally refuses `frozen_ohlc_model`, `quote_observed_virtual_v1`
and other virtual books: their $1,000 modeled balances use different executions
and cannot be compared as the absolute NAV of this Alpaca paper account.

No matched broker shadow ledger was discovered during implementation. Thus a
successful broker snapshot alone still reports `nav_reconciliation:not_established`.
A mismatch reports `blocked_balance_or_position_mismatch`; no existing trading
runtime is enabled or disabled by this separate evidence tool.

Collect the capture receipt first, independently reconstruct its matched shadow
ledger, then check entirely offline with no authentication or HTTP request:

```
python3 ~/.schafferai/apex-broker-reconciliation/broker_reconciliation.py \
  --snapshot-input /path/to/receipt.json --shadow /path/to/matched-shadow.json \
  --output ~/.schafferai/apex-broker-reconciliation/records
```

The output records the input receipt's exact-byte hash. Hashes establish source
identity, not the truth of an independently provided ledger.

## External-flow accounting interface

`flow_adjusted_pnl(previous_snapshot, current_snapshot, evidence)` computes dollar
P&L as `ending_equity - beginning_equity - deposits + withdrawals`. Evidence schema:

```
{
  "schema": "apex_external_flows/1", "account_number": "PA3YUD5NA",
  "currency": "USD", "after": "<previous capture_ended_utc>",
  "until": "<current capture_ended_utc>", "complete": true,
  "source_sha256": "<64-character independently verified flow-source hash>",
  "flows": [
    {"id": "deposit-id", "at_utc": "<aware time inside interval>",
     "kind": "deposit", "amount_usd": "15"}
  ]
}
```

Amounts are unsigned; kind determines direction. Duplicate IDs, incomplete
coverage, wrong scope/window and out-of-window flows refuse. An explicit complete
empty list represents verified no flows; an absent list is not zero flows.
The evidence producer must classify genuine capital deposits/withdrawals from
broker activities independently; fees/dividends/trading cashflows are not capital
flows. This module does not guess classifications or certify the producer's
completeness assertion. It intentionally returns null TWR and IRR: those require
additional valuations at flow times and methodology, and neither substitutes for
cash/position reconciliation. Paper-broker P&L is not actual trading profit.

For saved broker snapshots the CLI also accepts `--previous /path/to/prior.json`
and `--external-flows /path/to/verified-flows.json` together. These work with
`--snapshot-input` entirely offline and preserve the flow source hash.

## Validation and sources

`python3 -m unittest test_broker_reconciliation -q` uses fake transport only.
Checks cover account/currency gates, concurrent change, pagination and cycles,
GET allowlist/redirect refusal, sanitized failures, exact quantities, independent
cash identity, virtual-book/time/scope refusal, capital flows, and immutable receipts.
No broker order, live identity change or funding operation is part of validation.

Official documentation reviewed November 3, 2026:

- [Google OAuth session control and invalid_rapt](https://developers.google.com/identity/protocols/oauth2)
- [Cloud Run attached identity and metadata availability](https://docs.cloud.google.com/run/docs/securing/service-identity)
- [Workload Identity Federation prerequisites](https://docs.cloud.google.com/iam/docs/workload-identity-federation)
- [Secret Manager authentication](https://docs.cloud.google.com/secret-manager/docs/authentication)
- [Alpaca paper account GET](https://docs.alpaca.markets/us/reference/getaccount-1)
- [Activities and pagination](https://docs.alpaca.markets/us/reference/getaccountactivities-2)
- [Activity accounting fields](https://docs.alpaca.markets/us/docs/account-activities)
- [Portfolio history rounding and cashflow configuration](https://docs.alpaca.markets/us/reference/getaccountportfoliohistory-1)
