"""FastMCP auto-enables DNS-rebinding protection (mcp==1.29.0) with allowed_hosts limited
to localhost variants, captured at construction time when `host` defaults to "127.0.0.1" —
before server.py's `__main__` block rebinds to "0.0.0.0" for container use. That protection
then rejects the Host header a docker-compose peer sends (e.g. "supermarket-mcp:8001") with
421 Misdirected Request, discovered during CP9 live verification of the real
backend->MCP container network calls. Each server must explicitly allow its own
docker-compose service hostname alongside the localhost defaults.
"""

from mcp_servers.recipe_mcp import server as recipe_server
from mcp_servers.retailer_cart_mcp import server as retailer_cart_server
from mcp_servers.supermarket_mcp import server as supermarket_server
from tests.mcp.fakes import FakeSpoonacularClient


def test_supermarket_mcp_allows_its_own_compose_hostname():
    allowed_hosts = supermarket_server.mcp.settings.transport_security.allowed_hosts
    assert "supermarket-mcp:*" in allowed_hosts


def test_recipe_mcp_allows_its_own_compose_hostname():
    mcp_server = recipe_server.create_server(FakeSpoonacularClient())
    allowed_hosts = mcp_server.settings.transport_security.allowed_hosts
    assert "recipe-mcp:*" in allowed_hosts


def test_retailer_cart_mcp_allows_its_own_compose_hostname():
    mcp_server = retailer_cart_server.create_server(adapters={}, sessions_dir="sessions")
    allowed_hosts = mcp_server.settings.transport_security.allowed_hosts
    assert "retailer-cart-mcp:*" in allowed_hosts
