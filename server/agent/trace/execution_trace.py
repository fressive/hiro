"""Persisted tool and MCP trace normalization."""

import json
from typing import Any

from server.models.agent import AgentMessage


def attach_trace_metadata_fallback(messages: list[AgentMessage]) -> None:
    """Populate tool trace metadata for older messages that lack it."""
    if not messages:
        return

    assistant_messages = [
        message for message in messages if message.role == "assistant"
    ]
    if not assistant_messages:
        return

    if any(
        isinstance(message.extra_metadata, dict)
        and (
            message.extra_metadata.get("tool_events")
            or message.extra_metadata.get("mcp_events")
            or message.extra_metadata.get("subagent_events")
        )
        for message in assistant_messages
    ):
        return

    tool_events = reconstruct_tool_events(messages)
    target = next(
        (
            message
            for message in reversed(assistant_messages)
            if message.content or message.tool_calls
        ),
        assistant_messages[-1],
    )
    target.extra_metadata = {
        **(target.extra_metadata or {}),
        "tool_events": tool_events,
        "mcp_events": [],
        "subagent_events": [],
    }


def normalize_trace_metadata(messages: list[AgentMessage]) -> None:
    """Keep tool trace metadata on one assistant message per user turn."""
    group: list[AgentMessage] = []
    for message in messages:
        if message.role == "user" and group:
            normalize_trace_metadata_group(group)
            group = []
        group.append(message)

    if group:
        normalize_trace_metadata_group(group)


def normalize_trace_metadata_group(messages: list[AgentMessage]) -> None:
    trace_messages = [
        message
        for message in messages
        if message.role == "assistant" and has_trace_metadata(message)
    ]
    if len(trace_messages) <= 1:
        return

    target = max(
        trace_messages,
        key=lambda message: (
            trace_message_score(message),
            message.created_at,
            message.id,
        ),
    )
    for message in trace_messages:
        if message is target:
            continue
        clear_trace_metadata(message)


def has_trace_metadata(message: AgentMessage) -> bool:
    metadata = message.extra_metadata
    return bool(
        isinstance(metadata, dict)
        and (
            metadata.get("tool_events")
            or metadata.get("mcp_events")
            or metadata.get("subagent_events")
        )
    )


def trace_message_score(message: AgentMessage) -> int:
    content = (message.content or "").strip()
    has_tool_calls = bool(message.tool_calls)
    if content and not has_tool_calls and not content.startswith("Error:"):
        return 3
    if content and not has_tool_calls:
        return 2
    if content:
        return 1
    return 0


def clear_trace_metadata(message: AgentMessage) -> None:
    metadata = dict(message.extra_metadata or {})
    for key in ("tool_events", "mcp_events", "subagent_events"):
        metadata.pop(key, None)
    message.extra_metadata = metadata or None


def reconstruct_tool_events(messages: list[AgentMessage]) -> list[dict[str, Any]]:
    events: list[dict[str, Any]] = []
    by_id: dict[str, dict[str, Any]] = {}

    for message in messages:
        if message.role == "assistant":
            for tool_call in message.tool_calls or []:
                event_id = str(tool_call.get("id") or f"tool-{len(events) + 1}")
                event = {
                    "id": event_id,
                    "name": tool_call.get("name") or "tool",
                    "status": "running",
                    "input": json.dumps(
                        tool_call.get("args", {}),
                        ensure_ascii=True,
                        default=str,
                    ),
                }
                by_id[event_id] = event
                events.append(event)
        elif message.role == "tool":
            event_id = message.tool_call_id
            event = by_id.get(event_id) if event_id else None
            if event is None:
                event_id = event_id or f"tool-{len(events) + 1}"
                event = {
                    "id": event_id,
                    "name": message.name or "tool",
                    "status": "running",
                }
                by_id[event_id] = event
                events.append(event)
            event["status"] = "done"
            event["output"] = message.content

    return events
