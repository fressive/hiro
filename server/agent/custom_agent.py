"""Session-scoped agent runner with persistence and token accounting."""

import asyncio
from contextlib import AsyncExitStack, suppress
from typing import Callable

from server.agent.events.streaming import (
    AgentStreamEvent,
    StreamCallbackHandler,
    stream_event,
)
from server.agent.graph.execution_graph import AgentExecutionGraph
from server.agent.persistence.message_store import AgentMessageStore
from server.agent.runtime.agent_runtime import AgentRuntime
from server.agent.runtime.mcp_loader import load_mcp_tools
from server.agent.runtime.run_context import AgentRunContext
from server.agent.trace.execution_trace import GRAPH_EDGES, GRAPH_NODES
from server.core.logger import logger
from server.models.llm import LLMConfig
from server.schemas.agent import AgentRunRequest
from server.service.rag_service import RagService


class CustomAgent:
    """Run a configured agent for one application session and persist its history."""

    def __init__(
        self,
        *,
        session_id: int,
        session_title: str | None,
        payload: AgentRunRequest,
        config: LLMConfig,
        agent_configs: dict[str, LLMConfig] | None = None,
    ) -> None:
        self.session_id = session_id
        self.session_title = session_title
        self.payload = payload
        self.config = config
        self.agent_configs = agent_configs or {}
        self.input_text = payload.input.strip()
        self.rag_context = ""
        self.rag_sources: list[str] = []
        self._rag_loaded = False
        self._messages = AgentMessageStore(
            session_id=session_id,
            input_text=self.input_text,
            model=self.agent_configs.get("main_agent", config).model,
        )
        self._runtime = AgentRuntime(
            session_id=session_id,
            input_text=self.input_text,
            payload=payload,
            config=config,
            agent_configs=self.agent_configs,
        )
        self._execution_graph = AgentExecutionGraph(
            session_id=session_id,
            input_text=self.input_text,
            payload=payload,
            messages=self._messages,
            runtime=self._runtime,
            rag_context=lambda: self.rag_context,
        )

    async def start(
        self,
        queue: asyncio.Queue[AgentStreamEvent | None],
        *,
        on_task_started: Callable[[asyncio.Task], None] | None = None,
        on_task_done: Callable[[], None] | None = None,
    ) -> asyncio.Task:
        await self._load_rag_context()

        loop = asyncio.get_running_loop()
        callback = StreamCallbackHandler(queue, loop)

        await queue.put(
            stream_event(
                "session",
                {"id": self.session_id, "title": self.session_title},
            )
        )

        if self.rag_sources:
            await queue.put(stream_event("rag_search", {"sources": self.rag_sources}))

        await queue.put(
            stream_event(
                "graph_init",
                {
                    "nodes": GRAPH_NODES,
                    "edges": GRAPH_EDGES,
                },
            )
        )

        task = asyncio.create_task(self._run_agent(queue, callback, on_task_done))
        if on_task_started:
            on_task_started(task)
        return task

    async def _run_agent(
        self,
        queue: asyncio.Queue[AgentStreamEvent | None],
        callback: StreamCallbackHandler,
        on_task_done: Callable[[], None] | None,
    ) -> None:
        run_context: AgentRunContext | None = None
        try:
            exit_stack = AsyncExitStack()
            run_context = AgentRunContext(
                queue=queue,
                callback=callback,
                agent_done=asyncio.Event(),
                exit_stack=exit_stack,
            )
            # MCP sessions use anyio cancel scopes; enter and exit them in this
            # runner task so LangGraph node scheduling cannot split the scope.
            run_context.mcp_tools = await load_mcp_tools(
                self.payload.mcp_servers,
                exit_stack,
            )
            run_context.mcp_tools_loaded = True
            await self._execution_graph.ainvoke({"run": run_context})

        except Exception as exc:
            logger.error("Agent execution error: %s", exc)
            assistant_msg_id = (
                run_context.assistant_msg_id if run_context is not None else None
            )
            await self._messages.write_error_message(exc, assistant_msg_id)
            await queue.put(
                stream_event(
                    "error",
                    {"message": str(exc), "session_id": self.session_id},
                )
            )
        finally:
            if run_context is not None:
                await self._close_mcp_sessions(run_context)
                run_context.agent_done.set()
            update_task = run_context.update_task if run_context is not None else None
            if update_task and not update_task.done():
                update_task.cancel()
                with suppress(asyncio.CancelledError):
                    await update_task
            if on_task_done:
                on_task_done()
            await queue.put(None)

    async def _close_mcp_sessions(self, run: AgentRunContext) -> None:
        try:
            await run.exit_stack.aclose()
        except Exception as exc:
            logger.warning(
                "MCP session cleanup failed for session %s: %s",
                self.session_id,
                _exception_message(exc),
            )

    async def _load_rag_context(self) -> None:
        if self._rag_loaded or not self.payload.enable_rag:
            self._rag_loaded = True
            return

        try:
            hits = await RagService.search(self.input_text, limit=5)
            if hits:
                context_parts = []
                for hit in hits:
                    source = hit.get("title", "Unknown")
                    text = hit.get("text", "")
                    context_parts.append(f"--- Source: {source} ---\n{text}")
                    if source not in self.rag_sources:
                        self.rag_sources.append(source)
                self.rag_context = "\n\n".join(context_parts)
        except Exception as exc:
            logger.warning(
                "RAG retrieval failed for session %s: %s",
                self.session_id,
                exc,
            )
        finally:
            self._rag_loaded = True


def _exception_message(error: BaseException) -> str:
    if isinstance(error, BaseExceptionGroup):
        child_messages = [
            _exception_message(child)
            for child in error.exceptions
        ]
        detail = "; ".join(message for message in child_messages if message)
        summary = str(error) or error.__class__.__name__
        if detail and detail not in summary:
            return f"{summary}: {detail}"
        return summary
    return str(error) or error.__class__.__name__
