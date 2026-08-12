# retailer-cart-mcp in il-central-1 — Design

## Problem

Shufersal and Rami Levy both block traffic originating from AWS `us-east-1` at the
CDN/WAF layer (confirmed live for both: Shufersal returns a cached CloudFront custom-error
page from S3 for requests routed through the `IAD` edge while the same request via a
non-AWS, Israel-routed edge gets the real 2.8MB site; Rami Levy returns an explicit
Cloudflare `403` for the same `IAD`-routed request while a `TLV`-routed request gets `200`).
Confirmed via three independent methods: Playwright from the pod, a raw `curl` from the
EC2 host itself (no browser/session involved), and a same-moment comparison against a
non-AWS origin — ruling out session staleness, code bugs, and transient site outages.

This is not a bug in `retailer_cart_mcp`'s adapters — the adapters already do the right
thing (report a block, never guess). The problem is purely that `us-east-1` is not a
network origin either site will serve real content to.

An interim VPN-based workaround (Gluetun + Surfshark, Israel exit node) was added directly
to `infra/k8s/prod/retailer-cart-mcp/retailer-cart-mcp-deployment.yaml` outside this
design process. That approach masks the traffic's true origin specifically to defeat the
sites' access-control decision, which conflicts with this codebase's own stated principle
("a detected block is always reported... it is never worked around") and likely the
retailers' terms of service. This design replaces it with infrastructure that is
genuinely, not just apparently, located in Israel.

## Goal

Run `retailer-cart-mcp` from real infrastructure in AWS's `il-central-1` (Tel Aviv) region,
so its outbound requests to Shufersal/Rami Levy are genuinely Israel-origin — no traffic
masking. Remove the Gluetun/Surfshark sidecar entirely.

## Non-goals

- Moving anything else (backend, DB, other MCPs, monitoring, ArgoCD) to `il-central-1`. Only
  `retailer-cart-mcp` has a real requirement to run there.
- High availability / autoscaling for the `il-central-1` instance — single instance,
  matching this project's existing MVP-scope cost/complexity trade-offs (e.g. the
  no-NAT-gateway decision in `infra/tf/main.tf`).
- Cross-region Prometheus scraping / dashboards for the new instance. Can be added later;
  out of scope here.

## Architecture

```
us-east-1 (existing cluster)                  il-central-1 (new)
+----------------------+                      +---------------------------+
| backend (FastAPI)     |   HTTPS + API key    | EC2 t3.small               |
|  mcp_clients.py -------+-------------------->|  nginx (TLS via certbot)   |
|  RETAILER_CART_MCP_URL |                      |   -> retailer-cart-mcp    |
+----------------------+                      |      (Docker container)   |
                                                +---------------------------+
                                                Elastic IP + Route53 A record
                                                (retailer-cart.fursa.click)
```

`retailer-cart-mcp` is removed entirely from the `us-east-1` cluster (both `dev` and
`prod` — the Deployment, Service, and Gluetun/Surfshark Secret). A single EC2 instance in
`il-central-1` serves both environments, distinguished by an `X-Environment: dev|prod`
request header that selects which session directory (`/app/sessions/dev/` vs.
`/app/sessions/prod/`) to read from.

## Networking & security

- **Region**: `il-central-1` requires account-level opt-in
  (`aws account enable-region --region-name il-central-1`) before any resource can be
  created there. Not yet done — first step of implementation.
- **VPC**: the region's default VPC. No custom VPC — this is a single-instance stack, not
  worth the complexity of a dedicated one.
- **Security group**: inbound `443/tcp` from `0.0.0.0/0` (the API key is the actual
  authorization boundary, not source IP — the backend's outbound IP isn't static enough to
  usefully restrict on); inbound `22/tcp` from `var.admin_cidr` only, for maintenance.
  Outbound: unrestricted (matches the existing project's egress posture).
- **Elastic IP**: required so the public IP is stable across instance stop/restart — DNS
  and the TLS cert both depend on a fixed address.
- **DNS**: new `A` record `retailer-cart.fursa.click` in the same existing Route53 hosted
  zone (`fursa.click`) used by the rest of the project. Route53 is global, so this doesn't
  require any dependency on the `us-east-1` stack.
- **TLS**: Let's Encrypt via `certbot`, terminated by `nginx` on the instance, reverse-
  proxying to the `retailer-cart-mcp` container on `8003`. Not ACM — ACM's public certs
  don't expose an exportable private key for use with a plain `nginx` process (ACM is
  built for ALB/CloudFront/API Gateway integration, none of which apply to a standalone
  EC2 instance).

## Terraform structure

A new, small, independent Terraform stack (own directory, e.g. `infra/tf-il/`, own state)
— not a second provider block bolted onto the existing `infra/tf`. The existing stack has
been through repeated apply/destroy churn and drift this session; keeping the new stack
isolated means nothing about it can be affected by, or accidentally affect, the `us-east-1`
state.

Contents: `aws_instance` (Ubuntu, `t3.small`), `aws_eip` + association, `aws_security_group`,
`data "aws_route53_zone"` (existing zone, read-only lookup) + `aws_route53_record`. No
custom AMI/Packer build — a stock Ubuntu AMI plus a `user_data` script that installs
Docker, nginx, and certbot, and writes the initial `docker-compose.yml`.

## Application changes

- **`mcp_servers/retailer_cart_mcp/server.py`**: add a Starlette middleware that checks an
  `X-API-Key` header against `RETAILER_CART_MCP_API_KEY` (env var), rejecting with `401`
  on missing/mismatched key. Extend `allowed_hosts`/`allowed_origins`
  (`TransportSecuritySettings`, same mechanism fixed earlier this session for the
  `-svc` Kubernetes hostname) to include `retailer-cart.fursa.click`.
- **`app/agent/mcp_clients.py`**: `base_url` becomes a required env var
  (`RETAILER_CART_MCP_URL`) instead of the current cluster-internal DNS name; requests
  attach `X-API-Key` and `X-Environment: dev|prod` headers.
- **Removed**: `infra/k8s/{dev,prod}/retailer-cart-mcp/` (Deployment, Service, the
  `surfshark-gluetun` Secret reference) — no longer runs in the cluster at all.
- **Added**: `RETAILER_CART_MCP_URL` and a `RETAILER_CART_MCP_API_KEY` Secret to the
  backend Deployments in both `dev` and `prod`.

## Session secrets delivery

No Kubernetes on the new instance, so the existing `kubectl`-based
`sync-retailer-sessions.yml` pattern doesn't apply directly. A new workflow,
`sync-retailer-sessions-il.yml` (manual-dispatch, same SSH-based approach as the rest of
this project's `sync-*.yml` workflows), connects to the `il-central-1` instance and writes
session files directly to disk from GitHub Secrets. `retailer-cart-mcp` reads these as a
live-mounted directory, same as the current in-cluster volume-mount behavior — no
container restart needed after a sync.

**Shufersal only, for now.** Rami Levy's captured session is currently ~590KB (a full
serialized Vuex/Pinia store snapshot the site needs for correct cart-to-account linkage —
see the two `fix(retailer-cart-mcp)` commits from 2026-08-13 — trimming it back down
broke cart persistence, so it's no longer trimmed). That's too large for a practical
GitHub Secret. Until a real shrinking approach exists, `sync-retailer-sessions-il.yml`
only handles `sessions/{dev,prod}/shufersal.json` from `RETAILER_SESSION_SHUFERSAL_*`.
Rami Levy's session is transferred to the instance manually, out of band, by hand — not
through this workflow. Revisit once the size problem is actually solved.

Two new GitHub Secrets/variables: `IL_CENTRAL_1_HOST` (the stable Elastic IP, set once
after `terraform apply`, same role as today's `CONTROL_PLANE_IP`), and
`RETAILER_CART_MCP_API_KEY` (generated once, shared between the instance's `docker-compose`
env and the backend's Secret).

## Deployment & updates

Initial provisioning is one-time, via Terraform's `user_data`. Ongoing image updates (a
new `moataz189/retailer-cart-mcp` push to Docker Hub) go through a new manual-dispatch
workflow, `deploy-retailer-cart-il.yml`, that SSHes in and runs
`docker compose pull && docker compose up -d` — the same SSH-based update pattern already
established for this project's other infra, just without `kubectl`.

## Testing

- Before wiring the backend to it: a manual `curl` from the instance itself against both
  retailer sites, confirming real (non-blocked) responses — the same cheap verification
  approach used to diagnose this problem in the first place.
- Existing backend/MCP-client tests use `FakeRetailerCartClient` and shouldn't need
  behavior changes (the change is configuration — URL and headers — not logic). Add one
  small unit test asserting `mcp_clients.py` attaches the `X-API-Key` header when
  configured.
- Manual end-to-end check post-deployment: a real chat request through the app, confirming
  Shufersal/Rami Levy cart automation succeeds instead of the `not_found`/blocked result
  seen throughout this investigation.
