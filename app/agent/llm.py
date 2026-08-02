import os

from langchain_aws import ChatBedrockConverse


def get_llm():
    return ChatBedrockConverse(
        model=os.environ["BEDROCK_MODEL_ID"],
        region_name=os.environ.get("AWS_REGION", "us-east-1"),
        temperature=0,
    )
