# CP14 — Prometheus & Grafana Monitoring

Spec milestone: M5 (completes M5). Depends on: CP11, CP13.

> **As-built note (2026-08-11):** implemented as a structural migration of a separate,
> already-working infrastructure project (`polyaifursa`)'s `kube-prometheus-stack` Helm
> deployment, ServiceMonitor/PrometheusRule/Grafana-dashboard-sidecar pattern, and SNS
> Alertmanager wiring — not the raw hand-rolled Prometheus/Grafana Deployments originally
> sketched below (which were never implemented as written). This resolves a pre-existing
> inconsistency in this repo's own docs: `docs/plan.md`'s overview already anticipated
> `kube-prometheus-stack`/`ServiceMonitor` (not raw manifests); this checkpoint's original
> detailed steps disagreed with that overview. The actual implementation follows the
> overview.

## Goal

Instrument the backend with metrics that are genuinely measurable from this codebase (chat
request count/duration/status, MCP call outcomes by service, request-type breakdown,
clarification count, retailer choice count, cart-preparation outcomes, token usage), and
deploy `kube-prometheus-stack` (Prometheus + Grafana + Alertmanager) via Helm/ArgoCD to
scrape and visualize them across both `dev` and `prod`, with alerting to SNS.

## Application instrumentation (`app/metrics.py`)

All metrics live in one module (`app/metrics.py`, not `app/api/metrics.py` — it's imported
by both `app/agent/*` and `app/api/*`, so it can't live under the `api` package without an
`agent`-depends-on-`api` layering inversion):

| Metric | Type | Labels | Recorded in |
|---|---|---|---|
| `agent_chat_requests_total` | Counter | `status` (`success`/`clarification`/`retailer_choice`/`error`) | `app/api/routes/chat.py` |
| `agent_chat_request_duration_seconds` | Histogram | — | `app/api/routes/chat.py` |
| `agent_input_tokens_total` / `agent_output_tokens_total` | Counter | — | `app/agent/nodes/parse_request.py` (from `ChatBedrockConverse`'s `usage_metadata`, the only LLM call site in the graph) |
| `agent_request_type_total` | Counter | `request_type` (`recipe`/`grocery_list`/`general_chat`) | `app/agent/nodes/parse_request.py` |
| `mcp_call_total` | Counter | `mcp_service` (`supermarket`/`recipe`/`retailer_cart`), `status` | `app/agent/mcp_clients.py` (each client's `_call`) |
| `retailer_choice_total` | Counter | `retailer` | `app/api/routes/chat.py` |
| `cart_preparation_total` | Counter | `status` (`success`/`partial`/`blocked`) | `app/api/routes/chat.py` |
| `http_requests_total` / `http_request_duration_seconds_*` | Counter/Histogram | `handler`, `method`, `status` | `prometheus_fastapi_instrumentator` (generic per-route HTTP metrics, wired in `app/api/main.py`) |

`agent_input_tokens_total`/`agent_output_tokens_total` were not in the original CP14 sketch
(which used a hand-rolled `app_error_codes_total`/`ingestion_stale`/`retailer_cart_items_total`
metric set based on a Postgres-ingestion architecture this project never built) — they're the
metrics the migrated reference infrastructure's own Agent dashboard already expects, and this
backend's LLM does expose real `usage_metadata`, so they're genuinely measurable. Conversely,
`ingestion_stale`/`app_error_codes_total` were **not** implemented — they depend on ingestion
freshness tracking and a typed warning-code taxonomy this project's ingestion/finalize code
doesn't currently expose in a form worth instrumenting; adding real metrics only for what the
code genuinely measures, not for what would be nice to have, was a deliberate choice.

`GET /metrics` (`app/metrics.py`'s router, included in `app/api/main.py`) serves
`prometheus_client`'s whole default registry in Prometheus text format — verified live via a
built Docker image (`curl /metrics` returns both the custom counters above and the generic
`http_requests_total`/`http_request_duration_seconds_*` family).

## Cluster monitoring stack

- **Helm chart:** `prometheus-community/kube-prometheus-stack` (pinned `88.0.1` in
  `infra/argocd/monitoring.yaml`), values at `infra/k8s/monitoring/values.yaml` (committed,
  with a placeholder SNS ARN) and `values.yaml.tpl` (the `envsubst` template
  `.github/workflows/cluster.yaml` renders from Terraform's real SNS topic ARN output on
  every cluster provisioning run). `fullnameOverride: monitoring`; Prometheus retains 30d /
  2GiB (below its 3Gi PVC to leave WAL/compaction headroom); Grafana persists 1Gi; the
  dashboard sidecar auto-loads any ConfigMap labeled `grafana_dashboard: "1"`.
- **ServiceMonitor** (`infra/k8s/dev/backend/backend-servicemonitor.yaml`, and the `prod`
  equivalent): scrapes the `backend-svc` Service's `/metrics` port every 15s, following
  `kube-prometheus-stack`'s default `serviceMonitorSelector: {}` (select everything)
  convention — works identically in both namespaces without per-namespace RBAC wiring.
- **PrometheusRule** (`infra/k8s/common/monitoring/prometheus-rules.yaml`, cluster-scoped —
  applies to both `dev` and `prod`):
  - `BackendHighErrorRate`/`BackendCriticalErrorRate` (>5%/>25% of `agent_chat_requests_total`
    over 5m) — same PromQL shape as the migrated reference infrastructure's
    `AgentHighErrorRate`/`AgentCriticalErrorRate`, renamed to match this project's own
    metric/service names.
  - `BackendDown` (`up{job="backend-svc"} == 0` for 2m).
  - `MCPServiceHighFailureRate`/`MCPServiceUnavailable` — derived from the backend's own
    `mcp_call_total` counter, not from scraping each MCP server directly (none of the three
    expose their own `/metrics`, so "an MCP server is unavailable" is only observable through
    the backend's call outcomes).
  - `PodCrashLooping`/`PodNotReady` — generic, `kube-state-metrics`-based (ships with the
    chart already), new relative to the reference infrastructure's own rule set,
    satisfying the "pod not ready / excessive restart" requirement.
- **Alertmanager → SNS:** unchanged from the migrated reference's config (same inhibit rules,
  same `sns_configs` receiver) — comment updated to reference this project's own alert names.
  **Manual step required:** SNS email subscriptions cannot be auto-confirmed; whoever's email
  is in `alert_email` (`infra/tf/tfvars/<region>.tfvars`) must click the confirmation link
  AWS sends after the first `terraform apply`.
- **Grafana dashboards** (`infra/k8s/common/monitoring/`, ConfigMap-sidecar pattern):
  - `grafana-backend-dashboard.yaml` — new, this project's own: 9 panels covering chat error
    rate, request-latency percentiles (p50/p95/p99), chat requests/min by status, input/output
    tokens/min, MCP call failure rate by service, MCP calls/min by service+status, cart
    preparation results, retailer choice count, and requests by type (recipe/grocery-list/
    general). Built by adapting the reference's own Agent dashboard JSON (same panel
    structure/style) and appending 5 new panels for this project's own metrics.
  - `grafana-fastapi-observability-dashboard.yaml` — reused verbatim (generic, applies to any
    `prometheus_fastapi_instrumentator`-instrumented service; now genuinely populated since
    `app/api/main.py` wires the instrumentator — see "Application instrumentation" above).
  - `grafana-nginx-ingress-dashboard.yaml` — reused verbatim (upstream ingress-nginx
    dashboard, pinned to the same chart version as `infra/helm/ingress-nginx-values.yaml`).
- **Ingresses:** `grafana.<zone>` and `prometheus.<zone>` (`infra/k8s/common/monitoring/`),
  matching the same hostname-locals pattern as `argocd.<zone>` (CP10/CP11) and the
  `supermarket-{dev,prod}.<zone>` app hostnames.

## Validation performed (code + static validation only)

- [x] `helm template kube-prometheus-stack --version 88.0.1 -f
      infra/k8s/monitoring/values.yaml` — renders successfully; `ebs-sc` storageClassName,
      `retentionSize: 2GiB`, and the SNS receiver config all confirmed present in the
      rendered output.
- [x] `kubeconform` — `ServiceMonitor`/`PrometheusRule` (both dev and prod) and all three
      Grafana dashboard `ConfigMap`s validate against their CRD schemas (included in the
      48-manifest run reported under CP11).
- [x] Python: embedded dashboard JSON parses (`json.loads`), 9 panels present in the new
      backend dashboard.
- [x] `pytest` — 357 tests pass, including 6 new tests
      (`tests/api/test_metrics_endpoint.py`, `tests/agent/test_mcp_clients_metrics.py`)
      covering `/metrics`'s existence, `agent_chat_requests_total`/`agent_request_type_total`
      incrementing on a real chat turn, `retailer_choice_total`/`cart_preparation_total`
      incrementing after a cart is prepared, and `mcp_call_total` incrementing on both the
      success and error paths of each of the three MCP client classes.
- [x] `ruff check` — clean.
- [x] Live Docker smoke test: built `app/api/Dockerfile`, ran the container, confirmed
      `/health` and `/metrics` both respond and `/metrics` contains both the custom counters
      and the generic `http_requests_total`/`http_request_duration_seconds_*` family.

## Risks

- No cluster was actually bootstrapped in this environment (code + static validation only,
  per the same product decision as CP10/CP11) — real scrape behavior, dashboard rendering
  against live data, and SNS alert delivery are all unverified against a live stack.
- `agent_input_tokens_total`/`agent_output_tokens_total` only increment on the first turn of
  a conversation (`parse_request` is the only node that calls the LLM, and it doesn't re-run
  on a resumed/interrupted turn) — this is correct behavior (tokens really are only spent
  once per classification), not a bug, but worth noting so the dashboard's token panel isn't
  misread as "missing data" on multi-turn conversations.

## Notes

Alerting (SNS-backed, via Alertmanager) is included, unlike the original CP14 sketch which
deliberately stopped at dashboards-only — this follows the migrated reference
infrastructure's own alerting design, which was already available to reuse rather than
needing to be built from scratch.

## Definition of Done

- [x] Application instrumentation complete (`app/metrics.py`, wired into
      `app/api/routes/chat.py`, `app/agent/nodes/parse_request.py`,
      `app/agent/mcp_clients.py`, `app/api/main.py`) and tested (357 tests passing, 6 new).
- [x] `infra/k8s/monitoring/`, `infra/k8s/common/monitoring/`, `infra/argocd/monitoring.yaml`
      created and statically validated.
- [x] Committed with message referencing CP14. **M5 milestone complete at this point** (code
      + static validation; live cluster verification deferred per the product decision above).
