# CP14 — Prometheus & Grafana Monitoring

Spec milestone: M5 (completes M5). Depends on: CP11, CP13.

## Goal

Instrument the backend with the metrics spec §7 calls for (request latency, MCP call
success/failure rates, per-retailer ingestion success/staleness, error-code counts, and
retailer-cart-preparation success/failure/blocked rates), and deploy Prometheus + Grafana
into the cluster to scrape and visualize them across both `dev` and `prod`.

## Scope

Application-side metrics instrumentation, a `monitoring` namespace with Prometheus +
Grafana, and one dashboard covering the metrics above. Does not add alerting/paging (out of
scope for MVP — dashboards only).

## Deliverables

- `GET /metrics` on the backend exposes Prometheus-format metrics, including custom
  counters/gauges beyond the standard HTTP ones.
- Prometheus (in-cluster) scrapes both the `dev` and `prod` backend services.
- A Grafana dashboard shows request latency, MCP call outcomes, ingestion freshness per
  retailer, retailer-cart-preparation outcomes, and error-code counts.

## Files to Create

```
app/api/metrics.py
k8s/monitoring/namespace.yaml
k8s/monitoring/prometheus-configmap.yaml
k8s/monitoring/prometheus-deployment.yaml
k8s/monitoring/prometheus-service.yaml
k8s/monitoring/grafana-datasource-configmap.yaml
k8s/monitoring/grafana-dashboard-configmap.yaml
k8s/monitoring/grafana-deployment.yaml
k8s/monitoring/grafana-service.yaml
```

## Files to Modify

- `app/api/main.py` — wire `prometheus-fastapi-instrumentator` for HTTP metrics and expose
  `/metrics`.
- `app/agent/mcp_clients.py` — record `mcp_calls_total{server, status}` around each `_call`.
- `app/ingestion/pipeline.py` — record `ingestion_last_success_timestamp{retailer}` and
  `ingestion_stale{retailer}`.
- `app/agent/nodes/finalize.py` — record `app_error_codes_total{code}` for each warning code
  produced.
- `mcp_servers/retailer_cart_mcp/automation.py` — record `retailer_cart_items_total{status}`
  and `retailer_cart_runs_blocked_total{reason}`.
- `requirements.txt` — add `prometheus-client` and `prometheus-fastapi-instrumentator`
  (both runtime: the backend imports and serves them directly).

## Detailed Implementation Steps

### Application instrumentation

1. Write `app/api/metrics.py`:
   ```python
   from prometheus_client import Counter, Gauge

   MCP_CALLS = Counter(
       "mcp_calls_total", "MCP tool calls by server and outcome", ["server", "status"]
   )
   INGESTION_LAST_SUCCESS = Gauge(
       "ingestion_last_success_timestamp", "Unix timestamp of last successful ingestion", ["retailer"]
   )
   INGESTION_STALE = Gauge(
       "ingestion_stale", "1 if this retailer's data is currently considered stale, else 0", ["retailer"]
   )
   RETAILER_CART_ITEMS = Counter(
       "retailer_cart_items_total", "Retailer-cart automation outcomes per item", ["status"]
   )
   RETAILER_CART_RUNS_BLOCKED = Counter(
       "retailer_cart_runs_blocked_total", "Retailer-cart automation runs stopped by a site block", ["reason"]
   )
   ERROR_CODES = Counter(
       "app_error_codes_total", "Typed application error/warning codes", ["code"]
   )
   ```
2. Modify `app/api/main.py`:
   ```python
   from prometheus_fastapi_instrumentator import Instrumentator
   ...
   Instrumentator().instrument(app).expose(app)
   ```
3. Modify `app/agent/mcp_clients.py`'s `_call` methods on each client class to wrap the
   existing logic:
   ```python
   from app.api.metrics import MCP_CALLS

   async def _call(self, tool_name: str, arguments: dict) -> dict:
       try:
           async with streamablehttp_client(self.base_url) as (read, write, _):
               async with ClientSession(read, write) as session:
                   await session.initialize()
                   result = await session.call_tool(tool_name, arguments)
                   MCP_CALLS.labels(server=self._server_label, status="success").inc()
                   return result.structuredContent or {}
       except Exception:
           MCP_CALLS.labels(server=self._server_label, status="error").inc()
           raise
   ```
   Add a `_server_label` class attribute (`"recipe"`, `"supermarket_data"`,
   `"retailer_cart"`) to each of the three client classes.
4. Modify `app/ingestion/pipeline.py`'s `ingest_retailer_feed` to set
   `INGESTION_LAST_SUCCESS.labels(retailer=retailer).set(time.time())` on successful
   activation, and extend the existing `is_stale` helper (CP2) to also call
   `INGESTION_STALE.labels(retailer=retailer).set(1 if stale else 0)`.
5. Modify `app/agent/nodes/finalize.py` to increment `ERROR_CODES` for each warning code it
   appends (`product_not_found`, `budget_exceeded`, `dietary_conflict`, etc.):
   ```python
   from app.api.metrics import ERROR_CODES
   ...
   for warning in warnings:
       ERROR_CODES.labels(code=warning["code"]).inc()
   ```
6. Modify `mcp_servers/retailer_cart_mcp/automation.py`'s `prepare_cart_for_retailer` to
   increment `RETAILER_CART_ITEMS.labels(status=...)` for each `added`/`failed` item, and
   `RETAILER_CART_RUNS_BLOCKED.labels(reason=blocked_reason).inc()` when a block occurs.
7. Run the full existing test suite to confirm instrumentation didn't break any behavior
   (metrics calls are side effects and shouldn't affect assertions); add one small test,
   `tests/api/test_metrics_endpoint.py`, asserting `GET /metrics` returns 200 and contains
   `mcp_calls_total` after at least one MCP call has been made in the test.

### Cluster monitoring stack

8. Write `k8s/monitoring/namespace.yaml` (`monitoring` namespace).
9. Write `k8s/monitoring/prometheus-configmap.yaml` — scrapes both environments by static
   target (simplest option for a two-namespace cluster; full Kubernetes service-discovery
   RBAC is unnecessary complexity here):
   ```yaml
   apiVersion: v1
   kind: ConfigMap
   metadata:
     name: prometheus-config
     namespace: monitoring
   data:
     prometheus.yml: |
       global:
         scrape_interval: 15s
       scrape_configs:
         - job_name: supermarket-backend
           metrics_path: /metrics
           static_configs:
             - targets: ["backend.supermarket-dev.svc.cluster.local:8000"]
               labels: { environment: dev }
             - targets: ["backend.supermarket-prod.svc.cluster.local:8000"]
               labels: { environment: prod }
   ```
10. Write `k8s/monitoring/prometheus-deployment.yaml` (`prom/prometheus` image, mounting the
    ConfigMap above at `/etc/prometheus/prometheus.yml`) and `prometheus-service.yaml`
    (`type: NodePort`, port `9090`).
11. Write `k8s/monitoring/grafana-datasource-configmap.yaml`:
    ```yaml
    apiVersion: v1
    kind: ConfigMap
    metadata:
      name: grafana-datasources
      namespace: monitoring
    data:
      datasource.yaml: |
        apiVersion: 1
        datasources:
          - name: Prometheus
            type: prometheus
            access: proxy
            url: http://prometheus:9090
            isDefault: true
    ```
12. Write `k8s/monitoring/grafana-dashboard-configmap.yaml` — a small but real dashboard
    covering every metric from step 1:
    ```yaml
    apiVersion: v1
    kind: ConfigMap
    metadata:
      name: grafana-dashboards
      namespace: monitoring
    data:
      supermarket-assistant.json: |
        {
          "title": "Supermarket Assistant",
          "panels": [
            {
              "title": "Request latency (p95)",
              "type": "graph",
              "targets": [{"expr": "histogram_quantile(0.95, rate(http_request_duration_seconds_bucket[5m]))"}]
            },
            {
              "title": "MCP calls by server/outcome",
              "type": "graph",
              "targets": [{"expr": "sum by (server, status) (rate(mcp_calls_total[5m]))"}]
            },
            {
              "title": "Retailer feed staleness",
              "type": "stat",
              "targets": [{"expr": "ingestion_stale"}]
            },
            {
              "title": "Retailer-cart item outcomes",
              "type": "graph",
              "targets": [{"expr": "sum by (status) (rate(retailer_cart_items_total[15m]))"}]
            },
            {
              "title": "Retailer-cart runs blocked by reason",
              "type": "graph",
              "targets": [{"expr": "sum by (reason) (rate(retailer_cart_runs_blocked_total[15m]))"}]
            },
            {
              "title": "Error codes",
              "type": "graph",
              "targets": [{"expr": "sum by (code) (rate(app_error_codes_total[15m]))"}]
            }
          ]
        }
    ```
13. Write `k8s/monitoring/grafana-deployment.yaml` (`grafana/grafana` image, mounting both
    ConfigMaps above into `/etc/grafana/provisioning/datasources` and
    `/etc/grafana/provisioning/dashboards` respectively, admin password from a small
    `grafana-admin` Secret created manually like the app secrets in CP11) and
    `grafana-service.yaml` (`type: NodePort`, port `3000`).
14. Since `k8s/monitoring/` isn't watched by either ArgoCD `Application` from CP11 (those
    watch `k8s/dev` and `k8s/prod` only), apply this stack directly:
    `kubectl apply -f k8s/monitoring/`. (A third ArgoCD `Application` for `k8s/monitoring`
    is a reasonable future enhancement; not required by spec §7, which only requires dev/prod
    GitOps.)
15. `kubectl -n monitoring get pods` — confirm Prometheus and Grafana are running.
16. Open Grafana's NodePort in a browser, confirm the "Supermarket Assistant" dashboard
    loads with the Prometheus datasource already provisioned (no manual setup).
17. Generate some real traffic (a few chat requests, an ingestion run, an approved cart) and
    confirm the dashboard's panels populate with real, non-empty data within Prometheus's
    scrape interval.
18. Commit all files.

## Testing Tasks

- [ ] `test_metrics_endpoint.py` passes.
- [ ] `kubectl -n monitoring get pods` shows Prometheus and Grafana `Running`.
- [ ] Grafana dashboard loads and all six panels show real data after generating traffic.
- [ ] Confirm Prometheus successfully scrapes **both** the dev and prod backend targets
      (`kubectl -n monitoring port-forward svc/prometheus 9090:9090` then check
      `/targets` shows both as `UP`).

## Acceptance Criteria

Prometheus scrapes both environments; Grafana shows request latency, MCP call
success/failure rates, per-retailer data freshness, retailer-cart-preparation outcomes, and
error-code counts, all populated from real traffic.

## Risks

- Static scrape targets (rather than Kubernetes service discovery) mean adding a third
  environment later would require a manual Prometheus config change — acceptable for a
  fixed two-namespace MVP.

## Notes

This checkpoint deliberately stops at dashboards — no alerting/paging is built, since spec
§7 only requires "operational visibility," not incident response.

## Definition of Done

- [ ] Application instrumentation complete and tested.
- [ ] Monitoring stack deployed and dashboard verified against real traffic.
- [ ] Committed with message referencing CP14. **M5 milestone complete at this point.**
