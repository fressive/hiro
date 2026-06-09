"""Shared helpers for normalizing and rendering LangChain messages."""

import json
from typing import Any

from langchain_core.messages import AIMessage, BaseMessage, HumanMessage, ToolMessage

from server.agent.utils.tool_call_ids import normalize_model_messages


def normalize_result_messages(result_state: Any) -> list[BaseMessage]:
    if isinstance(result_state, dict):
        result_messages = result_state.get("messages", [])
    else:
        result_messages = result_state
    if not isinstance(result_messages, list):
        result_messages = [result_messages]
    return normalize_model_messages(result_messages)


def last_ai_message(messages: list[BaseMessage]) -> AIMessage | None:
    for message in reversed(messages):
        if isinstance(message, AIMessage):
            return message
    return None


def format_message_for_context(message: Any) -> str:
    label = message_role_label(message)
    parts: list[str] = []
    content = extract_message_text(message)
    if content:
        parts.append(content)

    tool_calls = getattr(message, "tool_calls", None)
    if tool_calls:
        parts.append("Tool calls: " + _json_text(tool_calls))

    if not parts:
        return ""
    return f"### {label}\n" + "\n".join(parts)


def message_role_label(message: Any) -> str:
    if isinstance(message, HumanMessage):
        return "User"
    if isinstance(message, AIMessage):
        return "Assistant"
    if isinstance(message, ToolMessage):
        name = getattr(message, "name", None) or "tool"
        return f"Tool: {name}"
    message_type = getattr(message, "type", None)
    if message_type:
        return str(message_type).title()
    return type(message).__name__


def extract_message_text(message: Any) -> str:
    content = getattr(message, "content", None)
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return _json_text(content)
    content_blocks = getattr(message, "content_blocks", None)
    if isinstance(content_blocks, list):
        return _json_text(content_blocks)
    return ""


def _json_text(value: Any) -> str:
    return json.dumps(value, ensure_ascii=True, default=str)
