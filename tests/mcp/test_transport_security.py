"""FastMCP auto-enables DNS-rebinding protection (mcp==1.29.0) with allowed_hosts limited
to localhost variants, captured at construction time when `host` defaults to "127.0.0.1" —
before server.py's `__main__` block rebinds to "0.0.0.0" for container use. That protection
then rejects the Host header a peer sends with 421 Misdirected Request — discovered twice:
first during CP9 live verification of docker-compose's "supermarket-mcp:8001" hostname,
then again live in the Kubernetes cluster, where the peer hostname is instead the Service
name with a "-svc" suffix (e.g. "recipe-mcp-svc:8002", per
infra/k8s/*/recipe-mcp/recipe-mcp-service.yaml) — a different string, not covered by the
docker-compose hostname alone. Each server must explicitly allow both its docker-compose
service hostname and its Kubernetes Service hostname, alongside the localhost defaults.
"""

from mcp_servers.recipe_mcp import server as recipe_server
from mcp_servers.retailer_cart_mcp import server as retailer_cart_server
from mcp_servers.supermarket_mcp import server as supermarket_server
from tests.mcp.fakes import FakeSpoonacularClient


def test_supermarket_mcp_allows_its_own_compose_hostname():
    allowed_hosts = supermarket_server.mcp.settings.transport_security.allowed_hosts
    assert "supermarket-mcp:*" in allowed_hosts


def test_supermarket_mcp_allows_its_own_k8s_service_hostname():
    allowed_hosts = supermarket_server.mcp.settings.transport_security.allowed_hosts
    assert "supermarket-mcp-svc:*" in allowed_hosts


def test_recipe_mcp_allows_its_own_compose_hostname():
    mcp_server = recipe_server.create_server(FakeSpoonacularClient())
    allowed_hosts = mcp_server.settings.transport_security.allowed_hosts
    assert "recipe-mcp:*" in allowed_hosts


def test_recipe_mcp_allows_its_own_k8s_service_hostname():
    mcp_server = recipe_server.create_server(FakeSpoonacularClient())
    allowed_hosts = mcp_server.settings.transport_security.allowed_hosts
    assert "recipe-mcp-svc:*" in allowed_hosts


def test_retailer_cart_mcp_allows_its_own_compose_hostname():
    mcp_server = retailer_cart_server.create_server(adapters={}, sessions_dir="sessions")
    allowed_hosts = mcp_server.settings.transport_security.allowed_hosts
    assert "retailer-cart-mcp:*" in allowed_hosts


def test_retailer_cart_mcp_allows_its_own_k8s_service_hostname():
    mcp_server = retailer_cart_server.create_server(adapters={}, sessions_dir="sessions")
    allowed_hosts = mcp_server.settings.transport_security.allowed_hosts
    assert "retailer-cart-mcp-svc:*" in allowed_hosts


def test_retailer_cart_mcp_allows_its_il_central_1_ec2_hostname():
    # infra/tf-il's standalone EC2 instance is reached via nginx forwarding requests with
    # Host: retailer-cart.fursa.click — a third hostname distinct from the docker-compose
    # and Kubernetes ones above, also rejected with 421 unless explicitly allowed.
    mcp_server = retailer_cart_server.create_server(adapters={}, sessions_dir="sessions")
    allowed_hosts = mcp_server.settings.transport_security.allowed_hosts
    assert "retailer-cart.fursa.click:*" in allowed_hosts
