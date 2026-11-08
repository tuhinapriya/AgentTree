from unittest.mock import MagicMock, patch

from backend.app.db import AgentTreeDB
from backend.app.services.bedrock import BedrockService


def test_bedrock_service_uses_real_model_result_when_aws_is_ready(tmp_path):
    database = AgentTreeDB(str(tmp_path / "bedrock-real.db"))
    database.create_run("run-real-bedrock", "customer-operations")
    database.create_agent("run-real-bedrock", "parent-agent", None, "parent", ["read_orders", "process_order"])
    database.create_agent("run-real-bedrock", "order-agent", "parent-agent", "order", ["read_orders", "process_order"])
    database.create_agent("run-real-bedrock", "account-agent", "parent-agent", "account", ["read_account"])

    service = BedrockService(database)
    service._aws_ready = True

    with patch.object(service, "_call_bedrock_for_delegation", return_value=[
        {"agent_id": "order-agent", "role": "order", "task": "Process the order.", "approved": True},
    ]):
        payload = service.delegate("run-real-bedrock", "parent-agent", "Process order ORD-104.")

    assert payload["delegations"][0]["agent_id"] == "order-agent"
    assert payload["delegations"][0]["role"] == "order"


def test_bedrock_delegation_uses_converse_request_format(tmp_path):
    database = AgentTreeDB(str(tmp_path / "bedrock-converse.db"))
    service = BedrockService(database)
    client = MagicMock()
    client.converse.return_value = {
        "output": {"message": {"content": [{"text": '{"delegations": []}'}]}}
    }

    with patch("boto3.client", return_value=client):
        assert service._call_bedrock_for_delegation("Review order", ["order"]) == []

    kwargs = client.converse.call_args.kwargs
    assert kwargs["modelId"] == service.model_id
    assert kwargs["messages"][0]["content"][0]["text"]
    assert kwargs["inferenceConfig"]["maxTokens"] == 256
