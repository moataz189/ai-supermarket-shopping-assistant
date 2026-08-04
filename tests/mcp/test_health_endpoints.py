from starlette.testclient import TestClient

from mcp_servers.recipe_mcp import server as recipe_server
from mcp_servers.retailer_cart_mcp import server as retailer_cart_server
from mcp_servers.supermarket_mcp import server as supermarket_server
from tests.mcp.fakes import FakeSpoonacularClient


def test_supermarket_mcp_health_returns_ok():
    client = TestClient(supermarket_server.mcp.streamable_http_app())

    response = client.get("/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_recipe_mcp_health_returns_ok():
    mcp_server = recipe_server.create_server(FakeSpoonacularClient())
    client = TestClient(mcp_server.streamable_http_app())

    response = client.get("/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_retailer_cart_mcp_health_returns_ok():
    mcp_server = retailer_cart_server.create_server(adapters={}, sessions_dir="sessions")
    client = TestClient(mcp_server.streamable_http_app())

    response = client.get("/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}
