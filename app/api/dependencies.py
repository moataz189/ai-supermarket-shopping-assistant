import os
from functools import lru_cache

from app.agent.checkpointer import get_checkpointer
from app.agent.graph import build_graph
from app.agent.llm import get_llm
from app.agent.mcp_clients import McpSupermarketDataClient


@lru_cache
def get_agent_app():
    client = McpSupermarketDataClient(
        base_url=os.environ.get("SUPERMARKET_MCP_URL", "http://localhost:8001/mcp")
    )
    return build_graph(client, get_llm(), get_checkpointer())
