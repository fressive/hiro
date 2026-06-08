"""Live agent stream events and callback handling."""

import asyncio
from dataclasses import dataclass
from typing import Any

from langchain_core.callbacks import BaseCallbackHandler

from server.agent.persistence import token_usage


@dataclass(frozen=True)
class AgentStreamEvent:
    event: str
    data: dict[str, Any]

    def as_json(self) -> dict[str, Any]:
        return {"event": self.event, "data": self.data}


def stream_event(event: str, data: dict[str, Any]) -> AgentStreamEvent:
    return AgentStreamEvent(event=event, data=data)


def is_mcp_tool_name(tool_name: str) -> bool:
    return tool_name.startswith("mcp__") or tool_name in {"mcp_search", "mcp_call"}


def tool_event_name(tool_name: str, phase: str) -> str:
    if is_mcp_tool_name(tool_name):
        return f"mcp_{phase}"
    return f"tool_{phase}"


def stream_text_segments(value: Any) -> list[tuple[str, str]]:
    """Extract visible text/thinking deltas from provider stream chunks."""
    if value is None:
        return []

    if isinstance(value, str):
        return [("text", value)] if value else []

    if isinstance(value, list):
        segments: list[tuple[str, str]] = []
        for item in value:
            segments.extend(stream_text_segments(item))
        return segments

    if isinstance(value, dict):
        block_type = value.get("type")
        if block_type in {"thinking", "reasoning"}:
            text = (
                value.get("thinking")
                or value.get("reasoning")
                or value.get("text")
                or ""
            )
            return [("thinking", text)] if text else []

        if block_type in {"text", "text_delta"}:
            text = value.get("text") or ""
            return [("text", text)] if text else []

        if block_type in {"tool_use", "tool_call", "input_json_delta"}:
            return []

        text = value.get("text")
        return [("text", text)] if isinstance(text, str) and text else []

    content = getattr(value, "content", None)
    if content is not None:
        return stream_text_segments(content)

    block_type = getattr(value, "type", None)
    if block_type in {"thinking", "reasoning"}:
        text = (
            getattr(value, "thinking", None)
            or getattr(value, "reasoning", None)
            or getattr(value, "text", None)
            or ""
        )
        return [("thinking", text)] if text else []

    if block_type in {"text", "text_delta"}:
        text = getattr(value, "text", "")
        return [("text", text)] if text else []

    return []


class StreamCallbackHandler(BaseCallbackHandler):
    def __init__(
        self,
        queue: asyncio.Queue[AgentStreamEvent | None],
        loop: asyncio.AbstractEventLoop,
    ):
        self._queue = queue
        self._loop = loop
        self._tool_names: list[str] = []
        self._mcp_names: list[str] = []
        self._tool_run_map: dict[str, str] = {}
        self._tool_events: list[dict[str, Any]] = []
        self._mcp_events: list[dict[str, Any]] = []
        self._token_buffer: list[str] = []
        self._usage: dict[str, int] = token_usage.empty_token_usage()

    @property
    def tool_names(self) -> list[str]:
        return self._tool_names

    @property
    def mcp_names(self) -> list[str]:
        return self._mcp_names

    @property
    def usage(self) -> dict[str, int]:
        return self._usage

    @property
    def tool_events(self) -> list[dict[str, Any]]:
        return [dict(event) for event in self._tool_events]

    @property
    def mcp_events(self) -> list[dict[str, Any]]:
        return [dict(event) for event in self._mcp_events]

    def _enqueue(self, event: str, data: dict) -> None:
        asyncio.run_coroutine_threadsafe(
            self._queue.put(stream_event(event, data)), self._loop
        )

    def emit_event(self, event: str, data: dict[str, Any]) -> None:
        """Publish a control event on the live stream."""

        self._enqueue(event, data)

    def snapshot(self) -> dict[str, Any]:
        """Capture streamed callback state before a retryable operation."""

        return {
            "tool_names": list(self._tool_names),
            "mcp_names": list(self._mcp_names),
            "tool_run_map": dict(self._tool_run_map),
            "tool_events": [dict(event) for event in self._tool_events],
            "mcp_events": [dict(event) for event in self._mcp_events],
            "token_buffer": list(self._token_buffer),
            "usage": dict(self._usage),
        }

    def rollback(self, snapshot: dict[str, Any]) -> None:
        """Restore streamed callback state after a failed retry attempt."""

        self._tool_names = list(snapshot.get("tool_names", []))
        self._mcp_names = list(snapshot.get("mcp_names", []))
        self._tool_run_map = dict(snapshot.get("tool_run_map", {}))
        self._tool_events = [
            dict(event) for event in snapshot.get("tool_events", [])
        ]
        self._mcp_events = [
            dict(event) for event in snapshot.get("mcp_events", [])
        ]
        self._token_buffer = list(snapshot.get("token_buffer", []))
        self._usage = dict(snapshot.get("usage", token_usage.empty_token_usage()))

    def _event_collection(self, tool_name: str) -> list[dict[str, Any]]:
        if is_mcp_tool_name(tool_name):
            return self._mcp_events
        return self._tool_events

    def _upsert_tool_event(self, tool_name: str, event: dict[str, Any]) -> None:
        events = self._event_collection(tool_name)
        event_id = event["id"]
        for index, existing in enumerate(events):
            if existing["id"] == event_id:
                events[index] = {**existing, **event}
                return
        events.append(event)

    def on_llm_new_token(self, token: Any, **kwargs: Any) -> None:
        segments = stream_text_segments(token)
        if not segments:
            chunk = kwargs.get("chunk")
            message = getattr(chunk, "message", None)
            segments = stream_text_segments(message)

        for segment_type, text in segments:
            self.record_token(text, segment_type=segment_type)

    def record_token(
        self,
        text: str,
        *,
        segment_type: str = "text",
        agent_name: str | None = None,
        include_in_assistant_text: bool = True,
    ) -> None:
        """Record a streamed text delta from event streaming."""

        if not text:
            return
        if include_in_assistant_text:
            self._token_buffer.append(text)
            self._enqueue("token", {"text": text, "type": segment_type})
            return

        self._enqueue(
            "subagent_token",
            {
                "agent": agent_name,
                "text": text,
                "type": segment_type,
            },
        )

    @property
    def token_text(self) -> str:
        return "".join(self._token_buffer)

    def on_llm_end(self, response: Any, **kwargs: Any) -> None:
        usage = token_usage.llm_result_token_usage(response)
        self.record_token_usage(usage)

    def record_token_usage(self, usage: Any) -> None:
        """Record token usage from a streamed message output."""

        usage = token_usage.normalize_token_usage(usage)
        if not token_usage.has_token_usage(usage):
            return

        self._usage = token_usage.add_token_usage(self._usage, usage)
        self._enqueue(
            "token_usage",
            {
                "usage": usage,
                "total_usage": self.usage,
            },
        )

    def on_tool_start(self, serialized: dict, input_str: str, **kwargs: Any) -> None:
        tool_name = serialized.get("name") or "tool"
        run_id = str(
            kwargs.get("run_id")
            or f"{tool_name}-{len(self._tool_events) + len(self._mcp_events) + 1}"
        )
        self.record_tool_start(
            tool_name=tool_name,
            event_id=run_id,
            input_text=str(input_str),
        )

    def on_tool_end(self, output: Any, **kwargs: Any) -> None:
        run_id = str(kwargs.get("run_id", ""))
        tool_name = self._tool_run_map.get(run_id, "tool")
        self.record_tool_end(
            tool_name=tool_name,
            event_id=run_id,
            output_text=str(output),
        )

    def on_tool_error(self, error: BaseException, **kwargs: Any) -> None:
        run_id = str(kwargs.get("run_id", ""))
        tool_name = self._tool_run_map.get(run_id, "tool")
        self.record_tool_error(
            tool_name=tool_name,
            event_id=run_id,
            output_text=str(error),
        )

    def record_tool_start(
        self,
        *,
        tool_name: str,
        event_id: str,
        input_text: str,
        agent_name: str | None = None,
    ) -> None:
        """Record a tool start event from callbacks or event streaming."""

        if is_mcp_tool_name(tool_name):
            self._mcp_names.append(tool_name)
        else:
            self._tool_names.append(tool_name)

        self._tool_run_map[event_id] = tool_name
        event = {
            "id": event_id,
            "name": tool_name,
            "status": "running",
            "input": input_text,
        }
        if agent_name:
            event["agent"] = agent_name
        self._upsert_tool_event(tool_name, event)

        data = {"id": event_id, "name": tool_name, "input": input_text}
        if agent_name:
            data["agent"] = agent_name
        self._enqueue(tool_event_name(tool_name, "start"), data)

    def record_tool_end(
        self,
        *,
        tool_name: str,
        event_id: str,
        output_text: str,
        agent_name: str | None = None,
    ) -> None:
        """Record a tool completion event from callbacks or event streaming."""

        event = {
            "id": event_id,
            "name": tool_name,
            "status": "done",
            "output": output_text,
        }
        if agent_name:
            event["agent"] = agent_name
        self._upsert_tool_event(tool_name, event)

        data = {"id": event_id, "name": tool_name, "output": output_text}
        if agent_name:
            data["agent"] = agent_name
        self._enqueue(tool_event_name(tool_name, "end"), data)

    def record_tool_error(
        self,
        *,
        tool_name: str,
        event_id: str,
        output_text: str,
        agent_name: str | None = None,
    ) -> None:
        """Record a tool error event from callbacks or event streaming."""

        event = {
            "id": event_id,
            "name": tool_name,
            "status": "error",
            "output": output_text,
        }
        if agent_name:
            event["agent"] = agent_name
        self._upsert_tool_event(tool_name, event)

        data = {"id": event_id, "name": tool_name, "output": output_text}
        if agent_name:
            data["agent"] = agent_name
        self._enqueue(tool_event_name(tool_name, "error"), data)

    def record_subagent_start(
        self,
        *,
        name: str | None,
        path: str,
        task_input: str | None,
    ) -> None:
        self._enqueue(
            "subagent_start",
            {"name": name, "path": path, "input": task_input},
        )
        self._enqueue(
            "subagent_status",
            {
                "name": name,
                "path": path,
                "status": "started",
                "input": task_input,
            },
        )

    def record_subagent_end(
        self,
        *,
        name: str | None,
        path: str,
        status: str | None,
        error: str | None = None,
    ) -> None:
        self._enqueue(
            "subagent_end",
            {"name": name, "path": path, "status": status, "error": error},
        )
        self._enqueue(
            "subagent_status",
            {"name": name, "path": path, "status": status, "error": error},
        )
