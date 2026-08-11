# CP17 — Live Price-Feed Ingestion (Shufersal + Rami Levy)

> Not part of the original 16-checkpoint plan (`docs/plan.md`) — CP2 always pointed at "CP11"
> as where real live ingestion would eventually replace the fixtures-only CLI it built, but
> CP11 (as actually implemented — see its own as-built note) never did this; it stayed
> Postgres/DynamoDB infrastructure only. This checkpoint is that follow-on work, requested
> and implemented later, in the same spirit as CP10-14's infra migration but for the
> application's data layer instead.

Depends on: CP2 (`app/ingestion/pipeline.py`'s `FeedType`/`ingest_retailer_feed`, unchanged
in shape), CP11/CP13 (prod's in-cluster Postgres, which this now actually writes to).

## Goal

Replace prod's nightly fixtures-only ingestion with real live data: a one-shot `PriceFull`
load (full catalog baseline) triggered once per prod deployment, and an hourly `Price`
(incremental delta) poll — for exactly Shufersal Online (StoreID 413) and Rami Levy Online
(StoreID 39), the two stores this project has always targeted. Dev is unchanged (still
fixtures, still SQLite).

## Both retailers' real download mechanisms were reverse-engineered by hand

Neither is documented anywhere as an API — both were found by inspecting the real, live
portals directly (page HTML, referenced JS bundles, and live HTTP round-trips), not guessed.
Full detail lives as module docstrings in `app/ingestion/downloaders/{shufersal,rami_levy}.py`;
summary:

**Shufersal** (`prices.shufersal.co.il`) — no login. `GET /FileObject/UpdateCategory
?catID={1|2}&storeId=413` (catID 1=Price, 2=PriceFull) returns an HTML fragment with exactly
one `<a href="https://pricesprodpublic.blob.core.windows.net/...">` — a SAS-signed Azure Blob
URL, directly downloadable, expiring after a few hours (never cached/stored — always
re-resolved from the listing on every run). The downloaded bytes are real gzip containing one
XML file whose schema (`StoreID`, `ItemCode`, `ItemName`, `ItemPrice`, `Quantity`, `UnitQty`)
already matched `app/ingestion/feeds/shufersal.py`'s existing parser exactly — confirmed live,
not assumed.

**Rami Levy** — published via a *shared, third-party* "Cerberus Web Client" FTP-over-HTTP
portal (`url.retail.publishedprices.co.il`), not a Rami Levy-specific site; many Israeli
chains use the same platform. Login: `GET /login` for a session cookie + CSRF token, `POST
/login/user` with the public, passwordless `username=RamiLevi` credential Rami Levy's own
price-transparency page publishes, and the CSRF token as a **form field** (not a header —
confirmed from the portal's own JS: it appends a hidden `csrftoken` field to every form on
submit). File listing: `POST /file/json/dir`, a DataTables server-side-processing endpoint,
filtered server-side via `sSearch`. Filenames for StoreID 39 specifically (confirmed via the
portal's own "Stores" metadata file — StoreName "מרלוג אינטרנט", StoreType 2) use a different,
lowercase, zero-padded convention (`pricefull<chain>-039-<YYYYMMDDHHMM>.gz`) than physical
branches. **The downloaded bytes are a ZIP archive, not gzip, despite the ".gz" extension** —
confirmed via `file`; the ZIP's one entry has this project's already-expected schema
(`StoreId`, `ChainId`, `ItemNm`, `ManufacturerName`, `PriceUpdateDate`) — physical branches
use a materially different schema, irrelevant here since only StoreID 39 is ever requested.
The portal's own TLS certificate doesn't cover the exact three-level hostname it's linked
from (`*.publishedprices.co.il` vs `url.retail.publishedprices.co.il`) — handled by keeping
full certificate-chain/CA validation and narrowly disabling only the hostname check (not a
blanket `verify=False`), see `rami_levy.py`'s `_ssl_context_without_hostname_check`.

## Architecture

```
app/ingestion/downloaders/
  __init__.py       # DownloadedFeed, FeedDownloader protocol, DownloadError
  _retry.py         # shared transient-network-failure retry (not HTTP-error retry)
  shufersal.py
  rami_levy.py
app/ingestion/feeds/
  units.py           # NEW — shared Hebrew UnitQty normalization (see below)
  shufersal.py        # unchanged schema-parsing logic, now uses units.normalize_unit
  rami_levy.py         # same
app/ingestion/pipeline.py   # + already_processed(), + source_filename threaded through
app/ingestion/run.py         # + --source live-full / live-delta, per-retailer isolation
```

Download logic (auth, file discovery, decompression) is fully separate from parsing
(`app/ingestion/feeds/*.py`, unchanged in shape) and DB activation
(`app/ingestion/pipeline.py`, unchanged in shape) — a downloader only ever returns raw,
already-decompressed XML bytes plus the source file's own metadata.

## Real live data was messier than either fixture assumed — normalized, not guessed

Live testing surfaced two real gaps neither original fixture covered:

- Shufersal's real feed includes `UnitQty="מטרים"` (meters, e.g. cable/rope sold by length) —
  the fixture never had a length-unit example.
- Rami Levy's real feed has **14 distinct `UnitQty` spellings** for what are really just 7
  physical units — punctuation/spacing variants of the same word (e.g. `מ"ל`/`מ'ל`/`מל` all
  mean milliliter) plus a few genuinely new units (מטר, ס"מ, קילו) — and one clearly-anomalous
  value, the literal string `"1"` (almost certainly a retailer data-entry mistake, not a
  real unit).

`app/ingestion/feeds/units.py` (new, shared by both parsers) strips punctuation noise first
(`"`, `'`, `׳`, `״`, spaces), then looks the normalized form up in one synonym table — so both
retailers recognize the same set of variants instead of maintaining two separately-incomplete
lists. A value still unrecognized after normalization (per an explicit product decision) is
**not** fatal to the whole feed: that one item is skipped with a `logger.warning` (retailer +
item_code + raw value), and the rest of the feed — tens of thousands of other items — still
activates normally. `m`/`cm` deliberately have no entry in `app/agent/quantity.py`'s
weight-conversion table, same as `unit` already doesn't — length isn't convertible with
weight/volume, so they're stored as plain metadata.

## Duplicate/failure tracking

`RetailerFeedStatus` (existing table, `app/db/models.py`) gained two nullable columns:
`last_full_filename`, `last_delta_filename` — tracked independently per feed type, so a new
`PriceFull` never makes an already-processed `Price` delta look reprocessable or vice versa.
`already_processed(session, retailer, feed_type, filename)` checks this before a download's
result is parsed/ingested; `ingest_retailer_feed`'s existing `session.begin()` transaction
(unchanged) means the filename is only ever recorded on a **successful** commit — a failed or
rolled-back ingestion never marks a file as processed, so it's retried on the next run rather
than silently skipped.

`app/ingestion/run.py`'s `run_live(feed_type)` loops both retailers independently: one
retailer's `DownloadError`/`FeedValidationError`/unexpected exception is logged (retailer,
feed_type, error — never credentials or raw feed bytes) and the loop continues to the other
retailer. Returns `False` if any retailer failed, so the process exits non-zero (visible to
Kubernetes/CI) without that failure ever being silent or blocking the other retailer.

## Kubernetes (prod only — dev keeps its fixtures-based nightly CronJob unchanged)

Replaced prod's previous nightly fixtures `CronJob` (which would otherwise overwrite real
live-ingested data with fake fixture data every night) with two resources:

- **`infra/k8s/prod/ingestion/ingestion-full-job.yaml`** — a `Job`, not a CronJob, annotated
  `argocd.argoproj.io/hook: PostSync` (runs once per prod sync — which itself only ever
  happens manually, since `infra/argocd/prod.yaml` has no automated sync policy) —
  `command: [..., "--source", "live-full"]`.
- **`infra/k8s/prod/ingestion/ingestion-delta-cronjob.yaml`** — hourly (`schedule: "0 * * *
  *"`), `--source live-delta`. `already_processed()` makes a run against an unchanged
  upstream file a safe no-op.

Both read `DATABASE_URL` from the same `postgres-credentials` Secret prod's
`supermarket-mcp`/`backend` already use (`infra/k8s/prod/postgres/`).

## Validation performed

- [x] **Live, end-to-end, twice**: `run_live(FeedType.PRICE_FULL)` and `run_live
      (FeedType.PRICE)` both actually downloaded, decompressed, parsed, and activated real
      data into a real SQLite DB for both retailers (15,654 / 392 Shufersal items;
      15,982 / 8 Rami Levy items — 20 Rami Levy items correctly skipped for the anomalous
      `"1"` unit). A second run correctly detected both retailers as already-processed and
      skipped them (`already_processed` verified working against real filenames).
- [x] **Live, inside the actual built Docker image** (`app/ingestion/Dockerfile`, the same
      image the K8s Job/CronJob reference) — `docker run ... python -m app.ingestion.run
      --source live-delta` succeeded end-to-end, confirming the image's dependencies
      (`httpx`, `psycopg`) and the K8s manifests' `command:` override both work as intended.
- [x] Three real bugs were found and fixed by this live testing, not by inspection alone:
      an SSL hostname-verification failure (Rami Levy's own cert doesn't cover the exact
      hostname it's linked from), a login-success check that broke under
      `follow_redirects=True` (`response.status_code` reflects the *followed* page, not the
      login POST's own 302), and an unpadded store-ID in the Rami Levy filename search
      (`"39"` vs the real `"-039-"` filenames).
- [x] `pytest` — 35 new tests (unit normalization variants incl. the "1" edge case, parser
      skip-with-warning behavior, downloader latest-file-selection logic via lightweight
      fakes — no HTTP mocking library needed since the relevant functions already take
      `client` as an explicit parameter, dedup tracking incl. per-feed-type independence and
      failed-feed-not-marked-processed, retailer-failure isolation in `run_live`); 398 tests
      pass overall (up from 363).
- [x] `ruff check` — clean.
- [x] `kubeconform` — both new K8s manifests validate.
- [x] `docker build` — the ingestion image builds cleanly with the new
      `app/ingestion/downloaders/` package and dependencies.

## Risks

- Both downloaders depend on unofficial, undocumented mechanics of two real external
  portals (HTML structure, a specific JS-bundle-derived JSON API, a third-party FTP-web
  product's exact form-field/CSRF convention) that could change without notice — there's no
  SLA or versioned API contract backing any of this. `DownloadError` messages are written to
  make a future breakage's symptom obvious (e.g. "no PriceFull file found" vs a raw
  stack trace), but a real portal change would still need a person to re-verify and patch the
  affected downloader, the same way this checkpoint's own findings were produced.
- Rami Levy's TLS hostname-check relaxation is scoped as narrowly as the underlying `ssl`
  module allows (`check_hostname=False` while keeping `CERT_REQUIRED`) but is still a
  deliberate deviation from full validation — acceptable here because the mismatch is a
  confirmed, understood first-party misconfiguration on a government-mandated public-data
  portal transmitting no confidential data, not a plausible attack indicator.
- No live cluster was bootstrapped in this environment — the `ingestion-full-job.yaml`'s
  ArgoCD PostSync hook behavior and the hourly CronJob's real-world scheduling are unverified
  against an actual ArgoCD/Kubernetes install; the ingestion logic itself is verified against
  real upstream data and a real Postgres-compatible SQLAlchemy flow (see CP11), just not the
  Kubernetes orchestration layer around it.
- Both retailers' real feed data required a shared unit-normalization layer that didn't exist
  before; if a genuinely new unit spelling appears later, the affected item(s) are skipped
  with a warning rather than blocking ingestion — intentional per the requested design, but
  means such items simply won't appear in the catalog until `units.py` is updated to
  recognize them.

## Definition of Done

- [x] `app/ingestion/downloaders/` created, both retailers verified live end-to-end.
- [x] `app/ingestion/feeds/units.py` created; both parsers use it; unrecognized units skip
      the one item, never the whole feed.
- [x] `app/db/models.py`/`app/ingestion/pipeline.py` extended for per-feed-type dedup
      tracking, verified live.
- [x] `app/ingestion/run.py` extended with `live-full`/`live-delta`, per-retailer isolated
      failure handling, verified live (including duplicate-skip on a second run).
- [x] `infra/k8s/prod/ingestion/{ingestion-full-job.yaml,ingestion-delta-cronjob.yaml}`
      created; prod's superseded fixtures CronJob removed; dev unchanged.
- [x] 35 new tests, 398 total passing; `ruff` clean; `kubeconform` clean.
- [x] Committed with message referencing CP17.
