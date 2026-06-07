"""Session-scoped agent runner with persistence and token accounting."""

import asyncio
from contextlib import AsyncExitStack, suppress
from typing import Any, Callable

from langchain_core.messages import AIMessage, BaseMessage
from langgraph.graph import END, START, StateGraph

from server.agent.events.streaming import (
    AgentStreamEvent,
    StreamCallbackHandler,
    stream_event,
)
from server.agent.persistence.message_store import AgentMessageStore, extract_message_text
from server.agent.runtime.agent_runtime import AgentRuntime
from server.agent.runtime.mcp_loader import load_mcp_tools
from server.agent.runtime.run_context import AgentGraphState, AgentRunContext
from server.agent.subagents.writeup_agent import (
    WriteupAgent,
    save_writeup_artifact,
    should_generate_writeup,
)
from server.agent.trace.execution_trace import GRAPH_EDGES, GRAPH_NODES
from server.agent.utils.tool_call_ids import normalize_ai_message_tool_call_ids
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
    ) -> None:
        self.session_id = session_id
        self.session_title = session_title
        self.payload = payload
        self.config = config
        self.input_text = payload.input.strip()
        self.rag_context = ""
        self.rag_sources: list[str] = []
        self._rag_loaded = False
        self._messages = AgentMessageStore(
            session_id=session_id,
            input_text=self.input_text,
            model=config.model,
        )
        self._runtime = AgentRuntime(
            session_id=session_id,
            input_text=self.input_text,
            payload=payload,
            config=config,
        )
        self._execution_graph = self._build_execution_graph()

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
            async with AsyncExitStack() as exit_stack:
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
                run_context.agent_done.set()
            update_task = run_context.update_task if run_context is not None else None
            if update_task and not update_task.done():
                update_task.cancel()
                with suppress(asyncio.CancelledError):
                    await update_task
            if on_task_done:
                on_task_done()
            await queue.put(None)

    def _build_execution_graph(self) -> Any:
        graph = StateGraph(AgentGraphState)
        graph.add_node("persist_input", self._graph_persist_input)
        graph.add_node("prepare_context", self._graph_prepare_context)
        graph.add_node("execute_agent", self._graph_execute_agent)
        graph.add_node("writeup", self._graph_writeup)
        graph.add_node("persist_output", self._graph_persist_output)
        graph.add_edge(START, "persist_input")
        graph.add_edge("persist_input", "prepare_context")
        graph.add_edge("prepare_context", "execute_agent")
        graph.add_conditional_edges(
            "execute_agent",
            self._route_after_execute,
            {
                "writeup": "writeup",
                "persist_output": "persist_output",
            },
        )
        graph.add_edge("writeup", "persist_output")
        graph.add_edge("persist_output", END)
        return graph.compile()

    def _route_after_execute(self, state: AgentGraphState) -> str:
        if self._should_generate_writeup():
            return "writeup"
        self._enqueue_graph_node(state["run"], "writeup", "skipped")
        return "persist_output"

    async def _graph_persist_input(
        self, state: AgentGraphState
    ) -> AgentGraphState:
        run = state["run"]
        await self._emit_graph_node(run, "persist_input", "running")
        try:
            run.user_msg_id = await self._messages.save_user_message()
            run.assistant_msg_id = await self._messages.create_assistant_placeholder()
            run.update_task = asyncio.create_task(
                self._messages.update_assistant_periodically(
                    run.assistant_msg_id,
                    run.callback,
                    run.agent_done,
                    lambda: self._run_metadata(run),
                )
            )
        except Exception:
            await self._emit_graph_node(run, "persist_input", "error")
            raise
        await self._emit_graph_node(run, "persist_input", "done")
        return {"run": run}

    async def _graph_prepare_context(
        self, state: AgentGraphState
    ) -> AgentGraphState:
        run = state["run"]
        await self._emit_graph_node(run, "prepare_context", "running")
        if run.user_msg_id is None or run.assistant_msg_id is None:
            await self._emit_graph_node(run, "prepare_context", "error")
            raise RuntimeError("Agent history persistence was not initialized")

        try:
            if not run.mcp_tools_loaded:
                run.mcp_tools = await load_mcp_tools(
                    self.payload.mcp_servers,
                    run.exit_stack,
                )
                run.mcp_tools_loaded = True
            run.history_messages = await self._messages.load_history(
                user_msg_id=run.user_msg_id,
                assistant_msg_id=run.assistant_msg_id,
            )
            run.full_system_prompt = self._runtime.build_system_prompt(
                mcp_tools=run.mcp_tools,
                rag_context=self.rag_context,
            )
        except Exception:
            await self._emit_graph_node(run, "prepare_context", "error")
            raise
        await self._emit_graph_node(run, "prepare_context", "done")
        return {"run": run}

    async def _graph_execute_agent(
        self, state: AgentGraphState
    ) -> AgentGraphState:
        run = state["run"]
        await self._emit_graph_node(run, "execute_agent", "running")
        try:
            run.all_messages = await self._runtime.execute(
                history_messages=run.history_messages,
                mcp_tools=run.mcp_tools,
                full_system_prompt=run.full_system_prompt,
                callback=run.callback,
            )
        except Exception:
            await self._emit_graph_node(run, "execute_agent", "error")
            raise
        await self._emit_graph_node(run, "execute_agent", "done")
        return {"run": run}

    async def _graph_writeup(self, state: AgentGraphState) -> AgentGraphState:
        run = state["run"]
        await self._emit_graph_node(run, "writeup", "running")
        try:
            writeup_message = await self._generate_writeup(run)
            run.writeup_text = extract_message_text(writeup_message)
            if run.writeup_text:
                await self._save_writeup_artifact(run.writeup_text)
            run.all_messages.append(writeup_message)
        except Exception:
            await self._emit_graph_node(run, "writeup", "error")
            raise
        await self._emit_graph_node(run, "writeup", "done")
        return {"run": run}

    async def _graph_persist_output(
        self, state: AgentGraphState
    ) -> AgentGraphState:
        run = state["run"]
        await self._emit_graph_node(run, "persist_output", "running")
        if run.assistant_msg_id is None:
            await self._emit_graph_node(run, "persist_output", "error")
            raise RuntimeError("Assistant placeholder was not initialized")

        try:
            run.agent_done.set()
            if run.update_task is not None:
                await run.update_task
                run.update_task = None

            new_messages = [
                normalize_ai_message_tool_call_ids(msg)
                if isinstance(msg, BaseMessage)
                else msg
                for msg in run.all_messages[len(run.history_messages) + 1 :]
            ]
            run.assistant_text = await self._messages.save_final_messages(
                new_messages=new_messages,
                assistant_msg_id=run.assistant_msg_id,
                callback_usage=run.callback.usage,
                callback_text=run.callback.token_text,
                run_metadata=self._run_metadata(run, persist_output_status="done"),
            )
            if run.writeup_text:
                run.assistant_text = run.writeup_text
            elif not run.assistant_text:
                run.assistant_text = run.callback.token_text

            await self._emit_graph_node(run, "persist_output", "done")
            await run.queue.put(
                stream_event(
                    "done",
                    {"text": run.assistant_text, "session_id": self.session_id},
                )
            )
        except Exception:
            await self._emit_graph_node(run, "persist_output", "error")
            raise
        return {"run": run}

    async def _emit_graph_node(
        self,
        run: AgentRunContext,
        node_id: str,
        status: str,
    ) -> None:
        self._set_graph_node_status(run, node_id, status)
        if run.assistant_msg_id is not None:
            await self._persist_trace_metadata(run)
        await run.queue.put(self._graph_node_event(node_id, status))

    def _enqueue_graph_node(
        self,
        run: AgentRunContext,
        node_id: str,
        status: str,
    ) -> None:
        self._set_graph_node_status(run, node_id, status)
        run.queue.put_nowait(self._graph_node_event(node_id, status))

    def _graph_node_event(self, node_id: str, status: str) -> AgentStreamEvent:
        return stream_event(
            "graph_node",
            {
                "id": node_id,
                "status": status,
            },
        )

    def _set_graph_node_status(
        self,
        run: AgentRunContext,
        node_id: str,
        status: str,
    ) -> None:
        for node in run.graph_nodes:
            if node["id"] == node_id:
                node["status"] = status
                return
        run.graph_nodes.append(
            {
                "id": node_id,
                "label": node_id,
                "status": status,
            }
        )

    def _run_metadata(
        self,
        run: AgentRunContext,
        *,
        persist_output_status: str | None = None,
    ) -> dict[str, Any]:
        graph_nodes = [dict(node) for node in run.graph_nodes]
        if persist_output_status is not None:
            for node in graph_nodes:
                if node["id"] == "persist_output":
                    node["status"] = persist_output_status
                    break
        return {
            "graph_nodes": graph_nodes,
            "graph_edges": GRAPH_EDGES,
            "tool_events": run.callback.tool_events,
            "mcp_events": run.callback.mcp_events,
        }

    async def _persist_trace_metadata(self, run: AgentRunContext) -> None:
        if run.assistant_msg_id is None:
            return
        await self._messages.persist_trace_metadata(
            assistant_msg_id=run.assistant_msg_id,
            metadata=self._run_metadata(run),
        )

    def _should_generate_writeup(self) -> bool:
        return should_generate_writeup(self.input_text)

    async def _generate_writeup(self, run: AgentRunContext) -> AIMessage:
        writeup_agent = WriteupAgent(
            session_id=self.session_id,
            input_text=self.input_text,
            build_llm=self._runtime.build_llm,
            callback=run.callback,
        )
        return await writeup_agent.generate(
            all_messages=run.all_messages,
            history_messages=run.history_messages,
        )

    async def _save_writeup_artifact(self, report_markdown: str) -> None:
        save_writeup_artifact(self.session_id, report_markdown)

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
