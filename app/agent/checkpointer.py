import os

from langgraph.checkpoint.memory import MemorySaver


def get_checkpointer():
    backend = os.environ.get("CHECKPOINTER_BACKEND", "memory")
    if backend == "memory":
        return MemorySaver()
    if backend == "sqlite":
        from langgraph.checkpoint.sqlite import SqliteSaver

        return SqliteSaver.from_conn_string(os.environ.get("CHECKPOINTER_SQLITE_PATH", "checkpoints.db"))
    if backend == "dynamodb":
        from langgraph_checkpoint_aws import DynamoDBSaver

        table_name = os.environ.get("CHECKPOINT_DYNAMODB_TABLE")
        if not table_name:
            raise RuntimeError(
                "CHECKPOINT_DYNAMODB_TABLE is required when CHECKPOINTER_BACKEND=dynamodb — the "
                "table itself is provisioned by Terraform (infra/tf/main.tf's "
                "aws_dynamodb_table.langgraph_checkpoints), DynamoDBSaver does not create it."
            )
        return DynamoDBSaver(table_name=table_name, region_name=os.environ.get("AWS_REGION", "us-east-1"))
    raise ValueError(f"Unsupported CHECKPOINTER_BACKEND {backend!r}")
