"""Session-scoped live event fan-out for agent runs."""

from __future__ import annotations

import asyncio
from collections import deque

from server.agent.custom_agent import AgentStreamEvent


class SessionEventHub:
    """Fan out live agent events to WebSocket subscribers with bounded replay."""

    def __init__(self, *, max_replay_events: int = 5000) -> None:
        self._replay: deque[AgentStreamEvent] = deque(maxlen=max_replay_events)
        self._subscribers: set[asyncio.Queue[AgentStreamEvent | None]] = set()
        self._closed = False

    @property
    def has_subscribers(self) -> bool:
        return bool(self._subscribers)

    def reset_replay(self) -> None:
        self._replay.clear()

    async def publish(self, event: AgentStreamEvent) -> None:
        if self._closed:
            return

        self._replay.append(event)
        for queue in list(self._subscribers):
            await queue.put(event)

    async def publish_status(self, *, is_running: bool) -> None:
        await self.publish(
            AgentStreamEvent(
                event="status",
                data={"is_running": is_running},
            )
        )

    def subscribe(self, *, replay: bool) -> asyncio.Queue[AgentStreamEvent | None]:
        queue: asyncio.Queue[AgentStreamEvent | None] = asyncio.Queue()
        if self._closed:
            queue.put_nowait(None)
            return queue

        if replay:
            for event in self._replay:
                queue.put_nowait(event)
        self._subscribers.add(queue)
        return queue

    def unsubscribe(self, queue: asyncio.Queue[AgentStreamEvent | None]) -> None:
        self._subscribers.discard(queue)

    async def close(self) -> None:
        if self._closed:
            return

        self._closed = True
        for queue in list(self._subscribers):
            await queue.put(None)
        self._subscribers.clear()
