# retailer-cart-mcp in il-central-1 — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Run `retailer-cart-mcp` from a real EC2 instance in AWS `il-central-1` (Tel Aviv),
reachable from the existing `us-east-1` backend over HTTPS + API key, and remove it (and
its Gluetun/Surfshark VPN sidecar) from the `us-east-1` cluster entirely.

**Architecture:** Backend in `us-east-1` calls `retailer-cart-mcp` over the public internet
at `https://retailer-cart.fursa.click/mcp`, authenticated with an `X-API-Key` header and
scoped to dev/prod via an `X-Environment` header. The il-central-1 side is a single EC2
instance running Docker Compose (nginx/certbot for TLS, the `retailer-cart-mcp` container),
provisioned by a small, independent Terraform stack.

**Tech Stack:** Terraform (AWS provider), Docker Compose, nginx + certbot, FastMCP/Starlette
(Python), GitHub Actions (SSH-based, matching this project's existing `sync-*.yml`/
`cluster.yaml` patterns).

## Global Constraints

- `il-central-1` requires account-level opt-in before any resource can be created there.
- No VPN/traffic-masking of any kind — this whole feature exists specifically to replace
  one. See `docs/superpowers/specs/2026-08-12-il-central-1-retailer-cart-mcp-design.md`.
- Rami Levy's session sync is manual (out of band) for now — only Shufersal goes through
  the automated `sync-retailer-sessions-il.yml` workflow (design doc, "Session secrets
  delivery" section, updated 2026-08-13).
- Single EC2 instance, no autoscaling, no custom VPC — reuse the region's default VPC.
- `environment` (dev/prod) is implemented as an explicit MCP tool argument on
  `prepare_retailer_cart`, not a request header — simpler and avoids any dependency on
  FastMCP's `Context`/request-object access for this detail.

---

### Task 1: API key middleware + environment-scoped sessions in `retailer_cart_mcp/server.py`

**Files:**
- Modify: `mcp_servers/retailer_cart_mcp/server.py`
- Test: `tests/mcp/test_retailer_cart_mcp_server.py` (new)

**Interfaces:**
- Consumes: `RETAILER_CART_MCP_API_KEY` env var (required when set; if unset, the
  middleware is a no-op — this preserves today's docker-compose/local behavior where no
  key is configured at all).
- Produces: `create_server(adapters=ADAPTERS, sessions_dir=SESSIONS_DIR, api_key=None)` —
  `api_key` is a new optional parameter (defaults to `os.environ.get("RETAILER_CART_MCP_API_KEY")`
  at the `mcp = create_server()` call site, but explicit in the factory signature for
  testability). `prepare_retailer_cart`'s session path becomes
  `os.path.join(sessions_dir, environment, f"{retailer}.json")` where `environment` is
  read from the `X-Environment` request header via `ctx: Context`, defaulting to `"prod"`
  when the header is absent (matches this project's own prod-first convention elsewhere).

- [ ] **Step 1: Write the failing tests**

```python
# tests/mcp/test_retailer_cart_mcp_server.py
import pytest
from starlette.testclient import TestClient

from mcp_servers.retailer_cart_mcp.server import create_server


def test_missing_api_key_is_rejected_when_key_configured():
    server = create_server(adapters={}, sessions_dir="sessions", api_key="secret123")
    client = TestClient(server.streamable_http_app())
    response = client.post("/mcp", json={"jsonrpc": "2.0", "id": 1, "method": "ping"})
    assert response.status_code == 401


def test_correct_api_key_is_accepted():
    server = create_server(adapters={}, sessions_dir="sessions", api_key="secret123")
    client = TestClient(server.streamable_http_app())
    response = client.get("/health", headers={"X-API-Key": "secret123"})
    assert response.status_code == 200


def test_no_api_key_configured_is_a_no_op():
    # Matches today's docker-compose/local behavior — no key set, no enforcement.
    server = create_server(adapters={}, sessions_dir="sessions", api_key=None)
    client = TestClient(server.streamable_http_app())
    response = client.get("/health")
    assert response.status_code == 200
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/python -m pytest tests/mcp/test_retailer_cart_mcp_server.py -v`
Expected: FAIL — `create_server()` doesn't accept `api_key` yet. (`server.streamable_http_app()`
is confirmed to exist and return a real Starlette app supporting `.add_middleware` —
verified directly against the installed `mcp==1.29.0` before writing this plan.)

- [ ] **Step 3: Implement the API key middleware**

In `mcp_servers/retailer_cart_mcp/server.py`, add near the top (after existing imports):

```python
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import Response


class ApiKeyMiddleware(BaseHTTPMiddleware):
    def __init__(self, app, api_key: str | None):
        super().__init__(app)
        self._api_key = api_key

    async def dispatch(self, request, call_next):
        if self._api_key is not None and request.headers.get("X-API-Key") != self._api_key:
            return Response(status_code=401, content="invalid or missing X-API-Key")
        return await call_next(request)
```

Change `create_server`'s signature and body:

```python
def create_server(
    adapters: dict = ADAPTERS, sessions_dir: str = SESSIONS_DIR, api_key: str | None = None
) -> FastMCP:
    ...
    mcp = FastMCP(
        "retailer-cart",
        transport_security=TransportSecuritySettings(...),  # unchanged
    )
    mcp.streamable_http_app().add_middleware(ApiKeyMiddleware, api_key=api_key)
    ...
```

- [ ] **Step 4: Run tests to verify the middleware tests pass**

Run: `.venv/bin/python -m pytest tests/mcp/test_retailer_cart_mcp_server.py -v`
Expected: the three middleware tests PASS.

- [ ] **Step 5: Write the failing environment-scoping test**

```python
# add to tests/mcp/test_retailer_cart_mcp_server.py
import json
from pathlib import Path


async def test_prepare_retailer_cart_reads_environment_scoped_session(tmp_path, monkeypatch):
    sessions_dir = tmp_path / "sessions"
    (sessions_dir / "dev").mkdir(parents=True)
    (sessions_dir / "dev" / "shufersal.json").write_text(json.dumps({"cookies": [], "origins": []}))

    calls = []

    class _FakeAdapter:
        retailer_name = "shufersal"

    async def _fake_prepare(adapter, items, storage_state_path):
        calls.append(storage_state_path)
        return {
            "retailer": "shufersal", "added": [], "failed": [], "blocked": False,
            "blocked_reason": None, "cart_url": None,
        }

    monkeypatch.setattr(
        "mcp_servers.retailer_cart_mcp.server.prepare_cart_for_retailer", _fake_prepare
    )
    server = create_server(
        adapters={"shufersal": _FakeAdapter}, sessions_dir=str(sessions_dir), api_key=None
    )
    # Call the underlying tool function directly rather than through the transport —
    # simplest way to assert on storage_state_path without a full MCP client round trip.
    tool = server._tool_manager.get_tool("prepare_retailer_cart")
    await tool.fn(retailer="shufersal", items=[])
    assert calls == [str(sessions_dir / "dev" / "shufersal.json")]
```

Note: this test as written calls the tool with no way to supply the `X-Environment`
header (there's no live HTTP request in this direct-call path), so it will need the
`environment` parameter made an explicit, directly-settable argument on the tool function
in Step 6 below (not purely header-derived) — confirm this design choice by writing the
implementation to accept `environment: str = "prod"` as a plain tool parameter, and have
the *client* (`mcp_clients.py`, Task 3) supply it as a tool call argument rather than a
transport header. This is simpler and removes all uncertainty about `Context` header
access from FastMCP's tool layer — supersedes the header-based approach floated in the
design doc for this one detail. Update this test to pass `environment="dev"` explicitly
to `tool.fn(...)` once written this way.

- [ ] **Step 6: Implement environment-scoped session paths**

```python
@mcp.tool()
async def prepare_retailer_cart(
    retailer: str, items: list[CartItemRequest], environment: str = "prod"
) -> PrepareRetailerCartResponse:
    adapter_factory = adapters.get(retailer)
    if adapter_factory is None:
        return _refusal(retailer, items, "unsupported_retailer", "unsupported_retailer")

    session_path = os.path.join(sessions_dir, environment, f"{retailer}.json")
    _log_resolved_session_file(retailer, session_path)
    if not os.path.exists(session_path):
        return _refusal(retailer, items, "no_login_session", "login_required")

    result = await prepare_cart_for_retailer(
        adapter_factory(), [i.model_dump() for i in items], storage_state_path=session_path
    )
    return PrepareRetailerCartResponse(**result)
```

- [ ] **Step 7: Run all tests, verify pass**

Run: `.venv/bin/python -m pytest tests/mcp/test_retailer_cart_mcp_server.py -v`
Expected: all PASS.

- [ ] **Step 8: Wire `api_key` into the module-level `mcp` instance**

```python
mcp = create_server(api_key=os.environ.get("RETAILER_CART_MCP_API_KEY"))
```

- [ ] **Step 9: Full suite + lint**

Run: `.venv/bin/python -m pytest tests/ -q && .venv/bin/python -m ruff check mcp_servers/retailer_cart_mcp/`
Expected: all pass, no lint errors.

- [ ] **Step 10: Commit**

```bash
git add mcp_servers/retailer_cart_mcp/server.py tests/mcp/test_retailer_cart_mcp_server.py
git commit -m "feat(retailer-cart-mcp): add API key auth and per-environment session paths"
```

---

### Task 2: `mcp_clients.py` sends `X-API-Key` header and `environment` tool argument

**Files:**
- Modify: `app/agent/mcp_clients.py`
- Test: `tests/agent/test_mcp_clients_metrics.py` (extend)

**Interfaces:**
- Consumes: nothing new from other tasks (Task 1 defines what the server now expects).
- Produces: `McpRetailerCartClient(base_url: str, api_key: str | None = None, environment: str = "prod")`.
  `prepare_retailer_cart(retailer, items)` unchanged signature — `environment` is fixed at
  client-construction time (matches how one backend Deployment only ever serves one
  environment), not passed per-call.

- [ ] **Step 1: Write the failing test**

```python
# add to tests/agent/test_mcp_clients_metrics.py

async def test_retailer_cart_client_sends_api_key_header_and_environment_argument():
    captured = {}

    def _capturing_streamablehttp_client(url, headers=None, **kwargs):
        captured["headers"] = headers
        return _FakeAsyncContextManager((None, None, None))

    session = AsyncMock()
    session.initialize = AsyncMock()
    tool_result = AsyncMock()
    tool_result.structuredContent = {
        "retailer": "shufersal", "added": [], "failed": [], "blocked": False,
        "blocked_reason": None, "cart_url": None,
    }
    session.call_tool = AsyncMock(return_value=tool_result)

    with (
        patch("app.agent.mcp_clients.streamablehttp_client", side_effect=_capturing_streamablehttp_client),
        patch("app.agent.mcp_clients.ClientSession", return_value=_FakeAsyncContextManager(session)),
    ):
        client = McpRetailerCartClient(
            "https://retailer-cart.fursa.click/mcp", api_key="secret123", environment="dev"
        )
        await client.prepare_retailer_cart("shufersal", [])

    assert captured["headers"] == {"X-API-Key": "secret123"}
    session.call_tool.assert_awaited_once_with(
        "prepare_retailer_cart", {"retailer": "shufersal", "items": [], "environment": "dev"}
    )
```

- [ ] **Step 2: Run test, verify it fails**

Run: `.venv/bin/python -m pytest tests/agent/test_mcp_clients_metrics.py::test_retailer_cart_client_sends_api_key_header_and_environment_argument -v`
Expected: FAIL — `McpRetailerCartClient` doesn't accept `api_key`/`environment` yet.

- [ ] **Step 3: Implement**

In `app/agent/mcp_clients.py`, replace the `McpRetailerCartClient` class body:

```python
class McpRetailerCartClient:
    def __init__(self, base_url: str, api_key: str | None = None, environment: str = "prod"):
        self.base_url = base_url
        self._api_key = api_key
        self._environment = environment

    async def _call(self, tool_name: str, arguments: dict) -> dict | None:
        headers = {"X-API-Key": self._api_key} if self._api_key else None
        try:
            async with (
                streamablehttp_client(self.base_url, headers=headers) as (read, write, _),
                ClientSession(read, write) as session,
            ):
                await session.initialize()
                result = await session.call_tool(tool_name, arguments)
        except Exception:
            mcp_call_total.labels(mcp_service="retailer_cart", status="error").inc()
            raise
        mcp_call_total.labels(mcp_service="retailer_cart", status="success").inc()
        return result.structuredContent

    async def prepare_retailer_cart(self, retailer: str, items: list[dict]) -> dict:
        return await self._call(
            "prepare_retailer_cart",
            {"retailer": retailer, "items": items, "environment": self._environment},
        )
```

Note this duplicates `_call`'s body between `McpSupermarketDataClient`/`McpRecipeClient`/
`McpRetailerCartClient` slightly further (the `headers` line) — do not generalize this
into a shared base class as part of this task; the existing three classes are already
independent by design elsewhere in this file, and unifying them is out of scope here.

- [ ] **Step 4: Run test, verify it passes**

Run: `.venv/bin/python -m pytest tests/agent/test_mcp_clients_metrics.py -v`
Expected: all pass (existing tests too — `McpSupermarketDataClient`/`McpRecipeClient` are
untouched, `McpRetailerCartClient`'s existing error-counter test still passes since
`api_key`/`environment` default to `None`/`"prod"`).

- [ ] **Step 5: Full suite + lint**

Run: `.venv/bin/python -m pytest tests/ -q && .venv/bin/python -m ruff check app/agent/mcp_clients.py`

- [ ] **Step 6: Commit**

```bash
git add app/agent/mcp_clients.py tests/agent/test_mcp_clients_metrics.py
git commit -m "feat(agent): send API key header and environment to retailer-cart-mcp"
```

---

### Task 3: Wire new env vars through `dependencies.py` and both backend Deployments

**Files:**
- Modify: `app/api/dependencies.py`
- Modify: `infra/k8s/dev/backend/backend-deployment.yaml`
- Modify: `infra/k8s/prod/backend/backend-deployment.yaml`

**Interfaces:**
- Consumes: `McpRetailerCartClient(base_url, api_key, environment)` from Task 2.
- Produces: nothing consumed by later tasks — this is the final wiring point.

- [ ] **Step 1: Update `app/api/dependencies.py`**

Find the existing construction (currently `app/api/dependencies.py:19-20`):
```python
retailer_cart_client = McpRetailerCartClient(
    base_url=os.environ.get("RETAILER_CART_MCP_URL", "http://localhost:8003/mcp")
)
```
Replace with:
```python
retailer_cart_client = McpRetailerCartClient(
    base_url=os.environ.get("RETAILER_CART_MCP_URL", "http://localhost:8003/mcp"),
    api_key=os.environ.get("RETAILER_CART_MCP_API_KEY"),
    environment=os.environ.get("DEPLOYMENT_ENVIRONMENT", "prod"),
)
```

- [ ] **Step 2: Update `infra/k8s/dev/backend/backend-deployment.yaml`**

In the `env:` list, change the existing entry:
```yaml
            - name: RETAILER_CART_MCP_URL
              value: "http://retailer-cart-mcp-svc:8003/mcp"
```
to:
```yaml
            - name: RETAILER_CART_MCP_URL
              value: "https://retailer-cart.fursa.click/mcp"

            - name: DEPLOYMENT_ENVIRONMENT
              value: "dev"

            - name: RETAILER_CART_MCP_API_KEY
              valueFrom:
                secretKeyRef:
                  name: retailer-cart-mcp-api-key
                  key: RETAILER_CART_MCP_API_KEY
```

- [ ] **Step 3: Update `infra/k8s/prod/backend/backend-deployment.yaml`** the same way, with
      `DEPLOYMENT_ENVIRONMENT` value `"prod"` instead of `"dev"` (same `RETAILER_CART_MCP_URL`
      and `retailer-cart-mcp-api-key` Secret reference — both environments hit the same
      il-central-1 instance, distinguished only by the `environment` tool argument).

- [ ] **Step 4: Verify no Python tests reference the old default construction**

Run: `grep -rn "McpRetailerCartClient" app/ tests/` and confirm no test asserts on the
exact old two-argument call signature. (Existing tests construct `McpRetailerCartClient`
directly with just `base_url`, which still works since `api_key`/`environment` now default.)

Run: `.venv/bin/python -m pytest tests/ -q`
Expected: all pass, unchanged count from before this task.

- [ ] **Step 5: Commit**

```bash
git add app/api/dependencies.py infra/k8s/dev/backend/backend-deployment.yaml infra/k8s/prod/backend/backend-deployment.yaml
git commit -m "feat(backend): point retailer-cart-mcp client at il-central-1 endpoint"
```

Note: this Deployment change references a `retailer-cart-mcp-api-key` Secret that doesn't
exist yet in either namespace — Task 9's manual go-live checklist creates it (Task 7 only
syncs the Shufersal session file, not this Secret). Committing
this now is safe (ArgoCD will show the Deployment as degraded/pending until that Secret
exists, same class of ordering as any other Secret-dependent rollout in this project) but
**do not let ArgoCD sync this to a live cluster until Task 7's workflow has been run at
least once** — flag this explicitly when this plan reaches deployment.

---

### Task 4: Remove `retailer-cart-mcp` from the `us-east-1` cluster

**Files:**
- Delete: `infra/k8s/dev/retailer-cart-mcp/` (entire directory)
- Delete: `infra/k8s/prod/retailer-cart-mcp/` (entire directory)

**Interfaces:** none — purely subtractive, no other file depends on these paths (ArgoCD's
`dev`/`prod` Applications use `recurse: true` + `prune: true` over `infra/k8s/{dev,prod}`,
confirmed during the design phase — no `app-of-apps.yaml` or `infra/argocd/*.yaml` change
needed).

- [ ] **Step 1: Delete both directories**

```bash
git rm -r infra/k8s/dev/retailer-cart-mcp infra/k8s/prod/retailer-cart-mcp
```

- [ ] **Step 2: Confirm nothing else references these paths**

Run: `grep -rln "retailer-cart-mcp" infra/argocd/ infra/k8s/common/ 2>/dev/null`
Expected: no output (or only unrelated matches — inspect any hit before proceeding).

- [ ] **Step 3: Commit**

```bash
git commit -m "chore(k8s): remove retailer-cart-mcp and its Gluetun/Surfshark sidecar

Replaced by a standalone EC2 instance in il-central-1 — see
docs/superpowers/specs/2026-08-12-il-central-1-retailer-cart-mcp-design.md.
The VPN sidecar masked traffic origin to defeat a real access-control
decision by the retailers; this removes that entirely rather than
maintaining it."
```

**Do not push/merge this commit (or Task 3's) to `main`/`dev` until the il-central-1
instance is provisioned, its DNS record resolves, and its API key Secret exists in both
namespaces** — merging early would take down retailer-cart-mcp in prod with nothing yet
listening on the new endpoint. Hold this on the feature branch until Tasks 5-8 are done
and manually verified.

---

### Task 5: Terraform stack for the il-central-1 instance

**Files:**
- Create: `infra/tf-il/main.tf`
- Create: `infra/tf-il/variables.tf`
- Create: `infra/tf-il/outputs.tf`
- Create: `infra/tf-il/user-data.sh.tpl`
- Create: `infra/tf-il/tfvars/il-central-1.tfvars`

**Interfaces:**
- Consumes: nothing from other tasks.
- Produces: Terraform outputs `instance_public_ip` (the Elastic IP, used to set the
  `IL_CENTRAL_1_HOST` GitHub repo variable in Task 6) and `ssh_private_key` (sensitive,
  used to set the `IL_CENTRAL_1_SSH_KEY` GitHub secret in Task 6).

- [ ] **Step 1: Region opt-in (manual, one-time, not Terraform)**

```bash
aws account enable-region --region-name il-central-1
aws account get-region-opt-status --region-name il-central-1
```
Wait for `"RegionOptStatus": "ENABLED"` before proceeding (can take several minutes).

- [ ] **Step 2: Write `infra/tf-il/variables.tf`**

```hcl
variable "region" {
  type    = string
  default = "il-central-1"
}

variable "project_name" {
  type    = string
  default = "supermarket-assistant-retailer-cart"
}

variable "admin_cidr" {
  description = "Your IP in CIDR form, e.g. \"203.0.113.4/32\" (get it with: curl -s ifconfig.me) — used for SSH access only. No default: never accidentally left open."
  type        = string
}

variable "route53_zone_name" {
  description = "Existing Route53 public hosted zone, e.g. \"fursa.click\" — same zone the us-east-1 stack already manages. Route53 is global, so this has no dependency on that stack's state."
  type        = string
}

variable "hostname" {
  description = "Full hostname to create for this instance, e.g. \"retailer-cart.fursa.click\"."
  type        = string
}

variable "instance_type" {
  type    = string
  default = "t3.small"
}
```

- [ ] **Step 3: Write `infra/tf-il/main.tf`**

```hcl
terraform {
  required_version = ">= 1.7.0"
  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 6.0"
    }
    tls = {
      source  = "hashicorp/tls"
      version = "~> 4.0"
    }
  }

  backend "s3" {
    bucket = "moataz-terraform-state-bucket-2026"
    key    = "supermarket-assistant/retailer-cart-il-central-1.tfstate"
    region = "us-east-1"
    encrypt = true
  }
}

provider "aws" {
  region = var.region
  default_tags {
    tags = {
      Project   = var.project_name
      ManagedBy = "Terraform"
    }
  }
}

data "aws_vpc" "default" {
  default = true
}

data "aws_subnets" "default" {
  filter {
    name   = "vpc-id"
    values = [data.aws_vpc.default.id]
  }
}

data "aws_route53_zone" "this" {
  name         = var.route53_zone_name
  private_zone = false
}

# Ubuntu 24.04 LTS, official Canonical SSM parameter — resolved dynamically per-region so
# no AMI ID is ever hardcoded, matching this project's existing pattern for the us-east-1
# stack's own AMI lookup.
data "aws_ssm_parameter" "ubuntu_ami" {
  name = "/aws/service/canonical/ubuntu/server/24.04/stable/current/amd64/hvm/ebs-gp3/ami-id"
}

resource "tls_private_key" "this" {
  algorithm = "RSA"
  rsa_bits  = 4096
}

resource "aws_key_pair" "this" {
  key_name   = "${var.project_name}-key"
  public_key = tls_private_key.this.public_key_openssh
}

resource "aws_security_group" "this" {
  name        = "${var.project_name}-sg"
  description = "retailer-cart-mcp standalone EC2 instance"
  vpc_id      = data.aws_vpc.default.id

  ingress {
    description = "HTTPS"
    from_port   = 443
    to_port     = 443
    protocol    = "tcp"
    cidr_blocks = ["0.0.0.0/0"]
  }

  ingress {
    description = "SSH (admin only)"
    from_port   = 22
    to_port     = 22
    protocol    = "tcp"
    cidr_blocks = [var.admin_cidr]
  }

  egress {
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = ["0.0.0.0/0"]
  }
}

resource "aws_instance" "this" {
  ami                    = data.aws_ssm_parameter.ubuntu_ami.value
  instance_type          = var.instance_type
  subnet_id              = data.aws_subnets.default.ids[0]
  vpc_security_group_ids = [aws_security_group.this.id]
  key_name               = aws_key_pair.this.key_name

  metadata_options {
    http_tokens   = "required"
    http_endpoint = "enabled"
  }

  root_block_device {
    volume_type = "gp3"
    volume_size = 20
    encrypted   = true
  }

  user_data = templatefile("${path.module}/user-data.sh.tpl", {
    hostname = var.hostname
  })

  tags = { Name = var.project_name }
}

resource "aws_eip" "this" {
  instance = aws_instance.this.id
  domain   = "vpc"
  tags     = { Name = "${var.project_name}-eip" }
}

resource "aws_route53_record" "this" {
  zone_id = data.aws_route53_zone.this.zone_id
  name    = var.hostname
  type    = "A"
  ttl     = 300
  records = [aws_eip.this.public_ip]
}
```

- [ ] **Step 4: Write `infra/tf-il/user-data.sh.tpl`**

```bash
#!/bin/bash
set -euo pipefail

apt-get update
apt-get install -y docker.io docker-compose-v2 nginx certbot python3-certbot-nginx

systemctl enable --now docker

mkdir -p /opt/retailer-cart-mcp/sessions/dev /opt/retailer-cart-mcp/sessions/prod
cat > /opt/retailer-cart-mcp/docker-compose.yml <<'EOF'
services:
  retailer-cart-mcp:
    image: moataz189/retailer-cart-mcp:latest
    restart: unless-stopped
    ports: ["8003:8003"]
    environment:
      PORT: "8003"
      RETAILER_SESSIONS_DIR: /app/sessions
      RETAILER_CART_MCP_API_KEY: "$${RETAILER_CART_MCP_API_KEY}"
    volumes:
      - ./sessions:/app/sessions:ro
EOF

# Real cert/nginx config wiring happens on first manual login to this box (DNS must
# already resolve to this instance's Elastic IP before certbot can validate — which it
# will, since aws_route53_record and aws_eip are created together in the same apply).
cat > /etc/nginx/sites-available/retailer-cart <<EOF
server {
    listen 80;
    server_name ${hostname};
    location / {
        proxy_pass http://127.0.0.1:8003;
        proxy_http_version 1.1;
        proxy_set_header Host \$host;
        proxy_set_header X-Real-IP \$remote_addr;
    }
}
EOF
ln -sf /etc/nginx/sites-available/retailer-cart /etc/nginx/sites-enabled/retailer-cart
rm -f /etc/nginx/sites-enabled/default
systemctl reload nginx

certbot --nginx -d ${hostname} --non-interactive --agree-tos -m moataz.ody44@gmail.com --redirect
```

Note: `RETAILER_CART_MCP_API_KEY` is referenced in the compose file but not populated by
this `user_data` script — it's written by Task 7's `sync-retailer-sessions-il.yml`-adjacent
step (or a one-time manual `echo "RETAILER_CART_MCP_API_KEY=..." > /opt/retailer-cart-mcp/.env`
over SSH after provisioning, before the container is first started). Flag this explicitly
during manual setup — the container will start but reject all requests via Task 1's
middleware until this is set.

- [ ] **Step 5: Write `infra/tf-il/outputs.tf`**

```hcl
output "instance_public_ip" {
  value = aws_eip.this.public_ip
}

output "ssh_private_key" {
  value     = tls_private_key.this.private_key_pem
  sensitive = true
}
```

- [ ] **Step 6: Write `infra/tf-il/tfvars/il-central-1.tfvars`**

```hcl
admin_cidr        = "203.0.113.4/32" # replace with your real IP: curl -s ifconfig.me
route53_zone_name = "fursa.click"
hostname          = "retailer-cart.fursa.click"
```

- [ ] **Step 7: Validate**

```bash
cd infra/tf-il
terraform fmt -check -diff
terraform init
terraform validate
terraform plan -var-file=tfvars/il-central-1.tfvars
```
Expected: `fmt`/`validate` clean; `plan` shows resources to create with no errors (region
must already be opted-in from Step 1, or this fails with an auth/region error).

- [ ] **Step 8: Commit**

```bash
git add infra/tf-il
git commit -m "feat(infra): Terraform stack for retailer-cart-mcp in il-central-1"
```

**Do not `terraform apply` as part of this plan step** — per this project's established
pattern this session, infrastructure `apply`/`destroy` is run by the user directly, not
by an agent. Hand off here: tell the user the stack is ready for `terraform apply`.

---

### Task 6: `provision-il-central-1.yml` — persist the instance IP as a repo variable

**Files:**
- Create: `.github/workflows/provision-il-central-1.yml`

**Interfaces:** mirrors `cluster.yaml`'s IP-persistence pattern exactly. Produces the
`IL_CENTRAL_1_HOST` repo variable Task 8's workflow depends on.

- [ ] **Step 1: Write the workflow**

```yaml
name: Provision il-central-1 Instance

on:
  workflow_dispatch: {}

permissions:
  contents: write

jobs:
  terraform:
    name: Terraform Apply
    runs-on: ubuntu-latest
    defaults:
      run:
        working-directory: infra/tf-il

    steps:
      - name: Checkout repository
        uses: actions/checkout@v4

      - name: Configure AWS credentials
        uses: aws-actions/configure-aws-credentials@v4
        with:
          aws-access-key-id: ${{ secrets.AWS_ACCESS_KEY_ID }}
          aws-secret-access-key: ${{ secrets.AWS_SECRET_ACCESS_KEY }}
          aws-region: il-central-1

      - name: Setup Terraform
        uses: hashicorp/setup-terraform@v3
        with:
          terraform_wrapper: false

      - name: Terraform Init
        run: terraform init

      - name: Terraform Apply
        run: terraform apply -var-file=tfvars/il-central-1.tfvars -auto-approve

      - name: Persist instance IP as a repo variable
        env:
          GH_TOKEN: ${{ secrets.VARS_PAT || secrets.GITHUB_TOKEN }}
        run: |
          IP=$(terraform output -raw instance_public_ip)
          gh variable set IL_CENTRAL_1_HOST --body "$IP" --repo "${{ github.repository }}"

      - name: Print SSH private key for one-time manual retrieval
        run: |
          echo "::warning::Retrieve the SSH private key with: terraform output -raw ssh_private_key (run locally, not in CI — do not print it in a public log)."
```

Note the last step deliberately does NOT print the sensitive private key to the log — it's
retrieved locally by running `terraform output -raw ssh_private_key` from the same
`infra/tf-il` directory after `apply`, then saved as the `IL_CENTRAL_1_SSH_KEY` GitHub
secret by hand. This matches how `SSH_PRIVATE_KEY` is already handled for the main cluster
(never generated or exposed by a workflow).

- [ ] **Step 2: Validate YAML**

```bash
.venv/bin/python -c "import yaml; yaml.safe_load(open('.github/workflows/provision-il-central-1.yml'))" 2>&1 || python3 -c "import yaml" 2>&1
```
If `yaml` isn't installed, validate with `docker run --rm -v "$PWD":/w mikefarah/yq e . /w/.github/workflows/provision-il-central-1.yml` instead, or visually confirm indentation against the file above — do not skip validation entirely.

- [ ] **Step 3: Commit**

```bash
git add .github/workflows/provision-il-central-1.yml
git commit -m "feat(ci): workflow to provision the il-central-1 instance and persist its IP"
```

---

### Task 7: `sync-retailer-sessions-il.yml` — Shufersal session sync (manual)

**Files:**
- Create: `.github/workflows/sync-retailer-sessions-il.yml`

**Interfaces:** consumes `IL_CENTRAL_1_HOST` (Task 6) and `IL_CENTRAL_1_SSH_KEY` (manual,
see Task 6 note). Writes `sessions/{dev,prod}/shufersal.json` on the instance, matching
Task 1's `os.path.join(sessions_dir, environment, f"{retailer}.json")` path shape.

- [ ] **Step 1: Write the workflow**

```yaml
name: Sync Retailer Sessions (il-central-1, Shufersal only)

# Rami Levy's session (~590KB, a full Vuex/Pinia store snapshot the site needs for
# correct cart-to-account linkage — see the 2026-08-13 fix commits) is too large for a
# practical GitHub Secret and is transferred to the instance manually, out of band. This
# workflow only covers Shufersal until that's solved — see
# docs/superpowers/specs/2026-08-12-il-central-1-retailer-cart-mcp-design.md.
on:
  workflow_dispatch: {}

permissions:
  contents: read

concurrency:
  group: sync-retailer-sessions-il
  cancel-in-progress: true

jobs:
  sync:
    name: Sync Shufersal session to il-central-1
    runs-on: ubuntu-latest

    steps:
      - name: Require IL_CENTRAL_1_HOST
        run: |
          if [ -z "${{ vars.IL_CENTRAL_1_HOST }}" ]; then
            echo "IL_CENTRAL_1_HOST repo variable is not set — run 'Provision il-central-1 Instance' first." >&2
            exit 1
          fi

      - name: Sync sessions/{dev,prod}/shufersal.json
        uses: appleboy/ssh-action@v1
        env:
          SHUFERSAL_SESSION_DEV: ${{ secrets.RETAILER_SESSION_SHUFERSAL_DEV }}
          SHUFERSAL_SESSION_PROD: ${{ secrets.RETAILER_SESSION_SHUFERSAL_PROD }}
        with:
          host: ${{ vars.IL_CENTRAL_1_HOST }}
          username: ubuntu
          key: ${{ secrets.IL_CENTRAL_1_SSH_KEY }}
          envs: SHUFERSAL_SESSION_DEV,SHUFERSAL_SESSION_PROD
          script: |
            set -euo pipefail
            sudo mkdir -p /opt/retailer-cart-mcp/sessions/dev /opt/retailer-cart-mcp/sessions/prod
            echo "$SHUFERSAL_SESSION_DEV" | sudo tee /opt/retailer-cart-mcp/sessions/dev/shufersal.json > /dev/null
            echo "$SHUFERSAL_SESSION_PROD" | sudo tee /opt/retailer-cart-mcp/sessions/prod/shufersal.json > /dev/null
            sudo chmod 600 /opt/retailer-cart-mcp/sessions/dev/shufersal.json /opt/retailer-cart-mcp/sessions/prod/shufersal.json
            echo "Shufersal sessions synced (dev + prod)."
```

- [ ] **Step 2: Validate YAML** (same approach as Task 6 Step 2)

- [ ] **Step 3: Commit**

```bash
git add .github/workflows/sync-retailer-sessions-il.yml
git commit -m "feat(ci): sync Shufersal session to il-central-1 (Rami Levy stays manual)"
```

---

### Task 8: `deploy-retailer-cart-il.yml` — image updates

**Files:**
- Create: `.github/workflows/deploy-retailer-cart-il.yml`

**Interfaces:** consumes `IL_CENTRAL_1_HOST`/`IL_CENTRAL_1_SSH_KEY` (same as Task 7).

- [ ] **Step 1: Write the workflow**

```yaml
name: Deploy retailer-cart-mcp to il-central-1

on:
  workflow_dispatch: {}

permissions:
  contents: read

concurrency:
  group: deploy-retailer-cart-il
  cancel-in-progress: true

jobs:
  deploy:
    name: Pull latest image and restart
    runs-on: ubuntu-latest

    steps:
      - name: Require IL_CENTRAL_1_HOST
        run: |
          if [ -z "${{ vars.IL_CENTRAL_1_HOST }}" ]; then
            echo "IL_CENTRAL_1_HOST repo variable is not set — run 'Provision il-central-1 Instance' first." >&2
            exit 1
          fi

      - name: Pull and restart
        uses: appleboy/ssh-action@v1
        with:
          host: ${{ vars.IL_CENTRAL_1_HOST }}
          username: ubuntu
          key: ${{ secrets.IL_CENTRAL_1_SSH_KEY }}
          script: |
            set -euo pipefail
            cd /opt/retailer-cart-mcp
            sudo docker compose pull
            sudo docker compose up -d
```

- [ ] **Step 2: Validate YAML** (same approach as Task 6 Step 2)

- [ ] **Step 3: Commit**

```bash
git add .github/workflows/deploy-retailer-cart-il.yml
git commit -m "feat(ci): manual-dispatch image deploy workflow for il-central-1"
```

---

### Task 9: Manual live verification (not automatable — requires real credentials/DNS)

This task has no code to write — it's the go-live checklist, run by the user, in order:

- [ ] `aws account enable-region --region-name il-central-1` (Task 5, Step 1) and wait for
      `ENABLED` status.
- [ ] `terraform apply` in `infra/tf-il` (locally, or via Task 6's workflow) — creates the
      instance, Elastic IP, and Route53 record.
- [ ] From the instance itself (SSH in with the Task 6-retrieved private key), run the same
      cheap verification `curl` used throughout this investigation against both
      `https://www.shufersal.co.il` and `https://www.rami-levy.co.il`, confirming real
      (non-blocked, non-403) responses — do not proceed until this is confirmed.
- [ ] Set `RETAILER_CART_MCP_API_KEY` (generate with `openssl rand -hex 32`) in three
      places: `/opt/retailer-cart-mcp/.env` on the instance (referenced by Task 5's
      `docker-compose.yml`), and as a Kubernetes Secret named `retailer-cart-mcp-api-key`
      (key `RETAILER_CART_MCP_API_KEY`) in both the `dev` and `prod` namespaces (Task 3
      depends on this Secret already existing before ArgoCD syncs).
- [ ] Run "Sync Retailer Sessions (il-central-1, Shufersal only)" (Task 7).
- [ ] Manually copy Rami Levy's session file to
      `/opt/retailer-cart-mcp/sessions/{dev,prod}/rami_levy.json` on the instance over SSH.
- [ ] `sudo docker compose up -d` in `/opt/retailer-cart-mcp` on the instance (first start,
      now that the API key and sessions exist).
- [ ] `curl https://retailer-cart.fursa.click/health` from anywhere — confirms nginx/certbot
      TLS termination and the container are both up.
- [ ] Merge Tasks 1-4's commits to `dev`, let ArgoCD sync, and send a real chat request
      through the app confirming Shufersal/Rami Levy cart automation succeeds — the actual
      end-to-end proof this whole feature exists for.
- [ ] Repeat for `prod` once `dev` is confirmed working.
