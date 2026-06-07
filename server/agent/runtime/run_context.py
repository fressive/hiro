"""Per-run state shared across custom agent graph nodes."""

import asyncio
from contextlib import AsyncExitStack
from dataclasses import dataclass, field
from typing import Any, TypedDict

from langchain_core.messages import BaseMessage

from server.agent.events.streaming import AgentStreamEvent, StreamCallbackHandler
from server.agent.trace.execution_trace import initial_graph_nodes


@dataclass
class AgentRunContext:
    queue: asyncio.Queue[AgentStreamEvent | None]
    callback: StreamCallbackHandler
    agent_done: asyncio.Event
    exit_stack: AsyncExitStack
    update_task: asyncio.Task | None = None
    assistant_msg_id: int | None = None
    user_msg_id: int | None = None
    mcp_tools: list[Any] = field(default_factory=list)
    history_messages: list[BaseMessage] = field(default_factory=list)
    full_system_prompt: str = ""
    all_messages: list[Any] = field(default_factory=list)
    assistant_text: str = ""
    writeup_text: str = ""
    mcp_tools_loaded: bool = False
    graph_nodes: list[dict[str, Any]] = field(default_factory=initial_graph_nodes)


class AgentGraphState(TypedDict):
    run: AgentRunContext
