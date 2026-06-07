"""Execution graph metadata and persisted trace normalization."""

import json
from typing import Any

from server.agent.subagents.writeup_agent import looks_like_writeup
from server.models.agent import AgentMessage


GRAPH_NODES = [
    {
        "id": "persist_input",
        "label": "Persist Input",
        "description": "Save the user request and assistant placeholder.",
    },
    {
        "id": "prepare_context",
        "label": "Prepare Context",
        "description": "Load history, MCP tools, RAG context, and prompts.",
    },
    {
        "id": "information_collect",
        "label": "Information Collect",
        "description": "Build a target information brief when requested.",
        "optional": True,
        "node_type": "agent",
        "agent_name": "information_collect_agent",
    },
    {
        "id": "execute_agent",
        "label": "Execute Agent",
        "description": "Run the selected agent with tools and skills.",
        "node_type": "agent",
        "agent_name": "main_agent",
    },
    {
        "id": "writeup",
        "label": "Writeup",
        "description": "Generate a report from prior steps when requested.",
        "optional": True,
        "node_type": "agent",
        "agent_name": "writeup_agent",
    },
    {
        "id": "persist_output",
        "label": "Persist Output",
        "description": "Save final messages and token usage.",
    },
]
GRAPH_EDGES = [
    {"from": "persist_input", "to": "prepare_context"},
    {
        "from": "prepare_context",
        "to": "information_collect",
        "condition": "information collection requested",
    },
    {"from": "prepare_context", "to": "execute_agent", "condition": "default"},
    {"from": "information_collect", "to": "execute_agent"},
    {"from": "execute_agent", "to": "writeup", "condition": "report requested"},
    {"from": "execute_agent", "to": "persist_output", "condition": "default"},
    {"from": "execute_agent", "to": "information_collect", "condition": "information collect request"},
    {"from": "writeup", "to": "persist_output"},
]


def initial_graph_nodes() -> list[dict[str, Any]]:
    return [
        {
            "id": node["id"],
            "label": node["label"],
            "description": node.get("description"),
            "optional": node.get("optional", False),
            "node_type": node.get("node_type"),
            "agent_name": node.get("agent_name"),
            "status": "pending",
        }
        for node in GRAPH_NODES
    ]


def attach_trace_metadata_fallback(messages: list[AgentMessage]) -> None:
    """Populate graph/tool trace metadata for older messages that lack it."""
    if not messages:
        return

    assistant_messages = [
        message for message in messages if message.role == "assistant"
    ]
    if not assistant_messages:
        return

    if any(
        isinstance(message.extra_metadata, dict)
        and message.extra_metadata.get("graph_nodes")
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
        "graph_nodes": fallback_graph_nodes(
            writeup_done=looks_like_writeup(target.content)
        ),
        "graph_edges": GRAPH_EDGES,
        "tool_events": tool_events,
        "mcp_events": [],
    }


def normalize_trace_metadata(messages: list[AgentMessage]) -> None:
    """Keep graph/tool trace metadata on one assistant message per user turn."""
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
            metadata.get("graph_nodes")
            or metadata.get("tool_events")
            or metadata.get("mcp_events")
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
    for key in ("graph_nodes", "graph_edges", "tool_events", "mcp_events"):
        metadata.pop(key, None)
    message.extra_metadata = metadata or None


def fallback_graph_nodes(*, writeup_done: bool) -> list[dict[str, Any]]:
    nodes: list[dict[str, Any]] = []
    for node in GRAPH_NODES:
        status = "done"
        if node["id"] == "information_collect":
            status = "skipped"
        if node["id"] == "writeup" and not writeup_done:
            status = "skipped"
        nodes.append(
            {
                "id": node["id"],
                "label": node["label"],
                "description": node.get("description"),
                "optional": node.get("optional", False),
                "node_type": node.get("node_type"),
                "agent_name": node.get("agent_name"),
                "status": status,
            }
        )
    return nodes


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
