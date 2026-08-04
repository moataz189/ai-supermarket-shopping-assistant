import socket
import threading
import time

import httpx
import pytest
from werkzeug.serving import make_server

from tests.mcp.mock_site_server import create_app


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


@pytest.fixture
def mock_site():
    """Starts a fresh mock retailer Flask app on its own thread/port per test."""
    app = create_app()
    port = _free_port()
    server = make_server("127.0.0.1", port, app)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    base_url = f"http://127.0.0.1:{port}"

    for _ in range(100):
        try:
            httpx.get(base_url, timeout=0.2)
            break
        except httpx.TransportError:
            time.sleep(0.05)
    else:
        raise RuntimeError("mock retailer site did not start in time")

    yield base_url

    server.shutdown()
    thread.join(timeout=2)
