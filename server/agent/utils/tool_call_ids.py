"""Utilities for keeping LangChain tool call IDs valid."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Any
from uuid import uuid4

from langchain.agents.middleware.types import (
    AgentMiddleware,
    ModelRequest,
    ModelResponse,
)
from langchain_core.messages import AIMessage, BaseMessage


def is_valid_tool_call_id(value: Any) -> bool:
    """Return whether a value can be used as a LangChain ToolMessage id."""
    return isinstance(value, str) and bool(value) and value != "None"


def normalize_ai_message_tool_call_ids(message: BaseMessage) -> BaseMessage:
    """Ensure every AI tool call has a non-empty string id."""
    if not isinstance(message, AIMessage) or not message.tool_calls:
        return message

    changed = False
    normalized_tool_calls = []
    normalized_ids: list[str] = []

    for tool_call in message.tool_calls:
        normalized = dict(tool_call)
        tool_call_id = normalized.get("id")
        if not is_valid_tool_call_id(tool_call_id):
            tool_call_id = f"call_{uuid4().hex}"
            normalized["id"] = tool_call_id
            changed = True
        normalized_ids.append(str(tool_call_id))
        normalized_tool_calls.append(normalized)

    content = message.content
    if isinstance(content, list):
        tool_call_index = 0
        normalized_content = []
        for block in content:
            if isinstance(block, dict) and block.get("type") in {"tool_call", "tool_use"}:
                normalized_block = dict(block)
                if (
                    tool_call_index < len(normalized_ids)
                    and normalized_block.get("id") != normalized_ids[tool_call_index]
                ):
                    normalized_block["id"] = normalized_ids[tool_call_index]
                    changed = True
                tool_call_index += 1
                normalized_content.append(normalized_block)
            else:
                normalized_content.append(block)
        content = normalized_content

    additional_kwargs = message.additional_kwargs
    if isinstance(additional_kwargs.get("tool_calls"), list):
        normalized_kwargs = dict(additional_kwargs)
        raw_tool_calls = []
        for index, raw_tool_call in enumerate(additional_kwargs["tool_calls"]):
            if isinstance(raw_tool_call, dict):
                normalized_raw = dict(raw_tool_call)
                if (
                    index < len(normalized_ids)
                    and normalized_raw.get("id") != normalized_ids[index]
                ):
                    normalized_raw["id"] = normalized_ids[index]
                    changed = True
                raw_tool_calls.append(normalized_raw)
            else:
                raw_tool_calls.append(raw_tool_call)
        normalized_kwargs["tool_calls"] = raw_tool_calls
        additional_kwargs = normalized_kwargs

    if not changed:
        return message

    return message.model_copy(
        update={
            "content": content,
            "tool_calls": normalized_tool_calls,
            "additional_kwargs": additional_kwargs,
        }
    )


def normalize_model_messages(messages: list[BaseMessage]) -> list[BaseMessage]:
    """Normalize tool call ids in a model response message list."""
    return [normalize_ai_message_tool_call_ids(message) for message in messages]


class ToolCallIdMiddleware(AgentMiddleware):
    """Patch provider responses that omit tool call ids before tools execute."""

    def wrap_model_call(
        self,
        request: ModelRequest,
        handler: Callable[[ModelRequest], ModelResponse],
    ) -> ModelResponse:
        response = handler(request)
        return ModelResponse(
            result=normalize_model_messages(response.result),
            structured_response=response.structured_response,
        )

    async def awrap_model_call(
        self,
        request: ModelRequest,
        handler: Callable[[ModelRequest], Awaitable[ModelResponse]],
    ) -> ModelResponse:
        response = await handler(request)
        return ModelResponse(
            result=normalize_model_messages(response.result),
            structured_response=response.structured_response,
        )
