"""Per-run state shared across custom agent graph nodes."""

import asyncio
from contextlib import AsyncExitStack
from dataclasses import dataclass, field
from typing import Any, TypedDict

from langchain_core.messages import AIMessage, BaseMessage

from server.agent.events.streaming import AgentStreamEvent, StreamCallbackHandler
from server.agent.trace.execution_trace import initial_graph_nodes


@dataclass
class AgentRunContext:
    """Mutable state for one graph execution.

    The LangGraph state only carries this object under the ``run`` key. Each
    graph node updates a focused part of it: persistence IDs, prepared context,
    agent outputs, streaming callbacks, resource cleanup handles, and graph
    trace metadata. See ``docs/agent-run-context.md`` for field-level semantics.
    """

    # Queue consumed by the WebSocket/API bridge. Graph nodes publish stream,
    # graph status, error, and done events through it.
    queue: asyncio.Queue[AgentStreamEvent | None]

    # Model callback collector for streamed text, token usage, tool events, and
    # MCP events.
    callback: StreamCallbackHandler

    # Signals the periodic assistant placeholder updater to flush and stop.
    agent_done: asyncio.Event

    # Owns run-scoped async resources, especially MCP sessions.
    exit_stack: AsyncExitStack

    # Background task that periodically writes live output and trace metadata
    # into the assistant placeholder.
    update_task: asyncio.Task | None = None

    # Database ids created at the start of the run.
    assistant_msg_id: int | None = None
    user_msg_id: int | None = None

    # Runtime context prepared before invoking the main agent.
    mcp_tools: list[Any] = field(default_factory=list)
    history_messages: list[BaseMessage] = field(default_factory=list)
    full_system_prompt: str = ""

    # Main-agent message output. In deep-agent mode this is the state message
    # list returned by DeepAgent; in simple mode it is normalized manually.
    all_messages: list[Any] = field(default_factory=list)

    # Final text emitted in the done event after persistence chooses the best
    # available assistant output.
    assistant_text: str = ""

    # Optional information collection output, persisted as its own agent
    # message and appended into the main-agent prompt.
    information_collect_message: AIMessage | None = None
    information_collect_text: str = ""

    # Optional report output. When present, it becomes the final assistant text.
    writeup_text: str = ""

    # Guard against loading MCP tools twice when the runner preloads them before
    # graph execution.
    mcp_tools_loaded: bool = False

    # Current graph status snapshot for live UI rendering and persisted trace
    # metadata.
    graph_nodes: list[dict[str, Any]] = field(default_factory=initial_graph_nodes)


class AgentGraphState(TypedDict):
    """LangGraph state wrapper.

    Keeping a single mutable context object avoids copying large message/tool
    lists between nodes while still making the state shape explicit.
    """

    run: AgentRunContext
