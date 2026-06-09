"""Per-run state shared across a custom agent execution."""

import asyncio
from contextlib import AsyncExitStack
from dataclasses import dataclass, field
from typing import Any

from langchain_core.messages import BaseMessage

from server.agent.events.streaming import AgentStreamEvent, StreamCallbackHandler


@dataclass
class AgentRunContext:
    """Mutable state for one agent execution."""

    # Queue consumed by the WebSocket/API bridge.
    queue: asyncio.Queue[AgentStreamEvent | None]

    # Model callback collector for streamed text, token usage, tool events, and
    # MCP events.
    callback: StreamCallbackHandler

    # Signals the periodic assistant placeholder updater to flush and stop.
    agent_done: asyncio.Event

    # Compatibility hook for older run setup paths that keep async resources
    # alive for the duration of one agent execution.
    exit_stack: AsyncExitStack | None = None

    # Background task that periodically writes live output and trace metadata
    # into the assistant placeholder.
    update_task: asyncio.Task | None = None

    # Database ids created at the start of the run.
    assistant_msg_id: int | None = None
    user_msg_id: int | None = None

    # Runtime context prepared before invoking the main agent.
    history_messages: list[BaseMessage] = field(default_factory=list)
    full_system_prompt: str = ""

    # Main-agent message output returned by DeepAgent.
    all_messages: list[Any] = field(default_factory=list)

    # Messages produced by the DeepAgent run and persisted after execution.
    generated_messages: list[Any] = field(default_factory=list)

    # Final text emitted in the done event after persistence chooses the best
    # available assistant output.
    assistant_text: str = ""
