"""LangGraph execution graph for session-scoped agent runs."""

import asyncio
from typing import Any, Callable

from langchain_core.messages import AIMessage, BaseMessage
from langgraph.graph import END, START, StateGraph

from server.agent.events.streaming import AgentStreamEvent, stream_event
from server.agent.persistence.message_store import AgentMessageStore, extract_message_text
from server.agent.runtime.agent_runtime import AgentRuntime
from server.agent.runtime.mcp_loader import load_mcp_tools
from server.agent.runtime.run_context import AgentGraphState, AgentRunContext
from server.agent.subagents.information_collect_agent import (
    InformationCollectAgent,
    append_information_collect_artifact,
    should_collect_information,
)
from server.agent.subagents.writeup_agent import (
    WriteupAgent,
    save_writeup_artifact,
    should_generate_writeup,
)
from server.agent.trace.execution_trace import GRAPH_EDGES
from server.agent.utils.tool_call_ids import normalize_ai_message_tool_call_ids
from server.schemas.agent import AgentRunRequest

MAIN_AGENT_NAME = "main_agent"
INFORMATION_COLLECT_AGENT_NAME = "information_collect_agent"
WRITEUP_AGENT_NAME = "writeup_agent"

class AgentExecutionGraph:
    """Build and run the session agent graph."""

    def __init__(
        self,
        *,
        session_id: int,
        input_text: str,
        payload: AgentRunRequest,
        messages: AgentMessageStore,
        runtime: AgentRuntime,
        rag_context: Callable[[], str],
    ) -> None:
        self.session_id = session_id
        self.input_text = input_text
        self.payload = payload
        self._messages = messages
        self._runtime = runtime
        self._rag_context = rag_context
        self._compiled_graph = self._build_execution_graph()

    def __getattr__(self, name: str) -> Any:
        return getattr(self._compiled_graph, name)

    async def ainvoke(self, *args: Any, **kwargs: Any) -> Any:
        return await self._compiled_graph.ainvoke(*args, **kwargs)

    def _build_execution_graph(self) -> Any:
        graph = StateGraph(AgentGraphState)
        graph.add_node("persist_input", self._graph_persist_input)
        graph.add_node("prepare_context", self._graph_prepare_context)
        graph.add_node("information_collect", self._graph_information_collect)
        graph.add_node("execute_agent", self._graph_execute_agent)
        graph.add_node("writeup", self._graph_writeup)
        graph.add_node("persist_output", self._graph_persist_output)
        graph.add_edge(START, "persist_input")
        graph.add_edge("persist_input", "prepare_context")
        graph.add_conditional_edges(
            "prepare_context",
            self._route_after_prepare_context,
            {
                "information_collect": "information_collect",
                "execute_agent": "execute_agent",
            },
        )
        graph.add_edge("information_collect", "execute_agent")
        graph.add_conditional_edges(
            "execute_agent",
            self._route_after_execute,
            {
                "writeup": "writeup",
                "persist_output": "persist_output",
                "information_collect": "information_collect",
            },
        )
        graph.add_edge("writeup", "persist_output")
        graph.add_edge("persist_output", END)
        return graph.compile()

    def _route_after_prepare_context(self, state: AgentGraphState) -> str:
        if should_collect_information(self.input_text):
            return "information_collect"
        return "execute_agent"

    def _route_after_execute(self, state: AgentGraphState) -> str:
        if should_generate_writeup(self.input_text):
            return "writeup"
        elif should_collect_information(self.input_text):
            return "information_collect"
        return "persist_output"

    async def _graph_persist_input(
        self,
        state: AgentGraphState,
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
                    lambda: self.run_metadata(run),
                )
            )
        except Exception:
            await self._emit_graph_node(run, "persist_input", "error")
            raise
        await self._emit_graph_node(run, "persist_input", "done")
        return {"run": run}

    async def _graph_prepare_context(
        self,
        state: AgentGraphState,
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
                rag_context=self._rag_context(),
            )
        except Exception:
            await self._emit_graph_node(run, "prepare_context", "error")
            raise
        await self._emit_graph_node(run, "prepare_context", "done")
        return {"run": run}

    async def _graph_information_collect(
        self,
        state: AgentGraphState,
    ) -> AgentGraphState:
        run = state["run"]
        await self._emit_graph_node(run, "information_collect", "running")
        try:
            information_collect_agent = InformationCollectAgent(
                session_id=self.session_id,
                input_text=self.input_text,
                build_llm=lambda: self._runtime.build_llm(
                    INFORMATION_COLLECT_AGENT_NAME
                ),
                callback=run.callback,
            )
            collection_message = _with_agent_name(
                await information_collect_agent.generate(
                    history_messages=run.history_messages,
                ),
                INFORMATION_COLLECT_AGENT_NAME,
            )
            run.information_collect_text = extract_message_text(collection_message)
            if run.information_collect_text:
                run.information_collect_message = collection_message
                append_information_collect_artifact(
                    self.session_id,
                    run.information_collect_text,
                )
                run.full_system_prompt = _append_information_collect_prompt(
                    run.full_system_prompt,
                    run.information_collect_text,
                )
        except Exception:
            await self._emit_graph_node(run, "information_collect", "error")
            raise
        await self._emit_graph_node(run, "information_collect", "done")
        return {"run": run}

    async def _graph_execute_agent(
        self,
        state: AgentGraphState,
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
            _tag_new_ai_messages(
                run.all_messages,
                start_index=len(run.history_messages) + 1,
                name=MAIN_AGENT_NAME,
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
            writeup_agent = WriteupAgent(
                session_id=self.session_id,
                input_text=self.input_text,
                build_llm=lambda: self._runtime.build_llm(WRITEUP_AGENT_NAME),
                callback=run.callback,
            )
            writeup_message = _with_agent_name(
                await writeup_agent.generate(
                    all_messages=run.all_messages,
                    history_messages=run.history_messages,
                ),
                WRITEUP_AGENT_NAME,
            )
            run.writeup_text = extract_message_text(writeup_message)
            if run.writeup_text:
                save_writeup_artifact(self.session_id, run.writeup_text)
            run.all_messages.append(writeup_message)
        except Exception:
            await self._emit_graph_node(run, "writeup", "error")
            raise
        await self._emit_graph_node(run, "writeup", "done")
        return {"run": run}

    async def _graph_persist_output(
        self,
        state: AgentGraphState,
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

            new_messages = []
            if run.information_collect_message is not None:
                new_messages.append(run.information_collect_message)

            new_messages.extend(
                normalize_ai_message_tool_call_ids(msg)
                if isinstance(msg, BaseMessage)
                else msg
                for msg in run.all_messages[len(run.history_messages) + 1 :]
            )
            run.assistant_text = await self._messages.save_final_messages(
                new_messages=new_messages,
                assistant_msg_id=run.assistant_msg_id,
                callback_usage=run.callback.usage,
                callback_text=run.callback.token_text,
                run_metadata=self.run_metadata(run, persist_output_status="done"),
                agent_models=self.agent_model_names(),
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

    def run_metadata(
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
            metadata=self.run_metadata(run),
        )

    def agent_model_names(self) -> dict[str, str]:
        return {
            INFORMATION_COLLECT_AGENT_NAME: self._runtime.agent_model_name(
                INFORMATION_COLLECT_AGENT_NAME
            ),
            MAIN_AGENT_NAME: self._runtime.agent_model_name(MAIN_AGENT_NAME),
            WRITEUP_AGENT_NAME: self._runtime.agent_model_name(WRITEUP_AGENT_NAME),
        }


def _append_information_collect_prompt(
    full_system_prompt: str,
    collection_markdown: str,
) -> str:
    section = (
        "INFORMATION COLLECTION BRIEF:\n"
        f"{collection_markdown.strip()}"
    )
    if not full_system_prompt.strip():
        return section
    return f"{full_system_prompt}\n\n{section}"


def _tag_new_ai_messages(
    messages: list[Any],
    *,
    start_index: int,
    name: str,
) -> None:
    for index in range(start_index, len(messages)):
        message = messages[index]
        if isinstance(message, AIMessage):
            messages[index] = _with_agent_name(message, name)


def _with_agent_name(message: AIMessage, name: str) -> AIMessage:
    try:
        message.name = name
        return message
    except Exception:
        return message.model_copy(update={"name": name})
