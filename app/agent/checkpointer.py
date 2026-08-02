import os

from langgraph.checkpoint.memory import MemorySaver


def get_checkpointer():
    backend = os.environ.get("CHECKPOINTER_BACKEND", "memory")
    if backend == "memory":
        return MemorySaver()
    if backend == "sqlite":
        from langgraph.checkpoint.sqlite import SqliteSaver

        return SqliteSaver.from_conn_string(os.environ.get("CHECKPOINTER_SQLITE_PATH", "checkpoints.db"))
    raise ValueError(f"Unsupported CHECKPOINTER_BACKEND {backend!r} as of CP4 ('dynamodb' is added in CP11)")
