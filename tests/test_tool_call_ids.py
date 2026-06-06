from langchain.agents.middleware.types import ModelResponse
from langchain_core.messages import AIMessage, ToolMessage

from server.agent.tool_call_ids import ToolCallIdMiddleware, normalize_ai_message_tool_call_ids


def test_normalize_ai_message_tool_call_ids_fills_missing_ids():
    message = AIMessage(
        content=[
            {
                "type": "tool_use",
                "id": None,
                "name": "log",
                "input": {"message": "hello"},
            }
        ],
        tool_calls=[
            {
                "type": "tool_call",
                "name": "log",
                "args": {"message": "hello"},
                "id": None,
            }
        ],
        additional_kwargs={
            "tool_calls": [
                {
                    "id": None,
                    "type": "function",
                    "function": {"name": "log", "arguments": '{"message":"hello"}'},
                }
            ]
        },
    )

    normalized = normalize_ai_message_tool_call_ids(message)
    tool_call_id = normalized.tool_calls[0]["id"]

    assert isinstance(tool_call_id, str)
    assert tool_call_id.startswith("call_")
    assert normalized.content[0]["id"] == tool_call_id
    assert normalized.additional_kwargs["tool_calls"][0]["id"] == tool_call_id
    assert ToolMessage(content="ok", tool_call_id=tool_call_id)


def test_tool_call_id_middleware_normalizes_model_response():
    message = AIMessage(
        content="",
        tool_calls=[
            {
                "type": "tool_call",
                "name": "log",
                "args": {"message": "hello"},
                "id": None,
            }
        ],
    )
    middleware = ToolCallIdMiddleware()

    response = middleware.wrap_model_call(
        None,  # type: ignore[arg-type]
        lambda _: ModelResponse(result=[message]),
    )

    assert response.result[0].tool_calls[0]["id"].startswith("call_")
