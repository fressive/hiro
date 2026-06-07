"""LangGraph execution graph for session-scoped agent runs."""

import asyncio
import json
from typing import Any, Callable

from langchain_core.messages import AIMessage, BaseMessage, HumanMessage, SystemMessage
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
from server.core.logger import logger
from server.schemas.agent import AgentRunRequest

MAIN_AGENT_NAME = "main_agent"
INFORMATION_COLLECT_AGENT_NAME = "information_collect_agent"
WRITEUP_AGENT_NAME = "writeup_agent"
PREPARE_ROUTE_ACTIONS = {
    "information_collect",
    "execute_agent",
}
POST_EXECUTE_ROUTE_ACTIONS = {
    "information_collect",
    "writeup",
    "persist_output",
}
MAX_POST_EXECUTE_ROUTE_DECISIONS = 8
MAX_INFORMATION_COLLECT_ROUTES = 3
ROUTE_CONTEXT_MAX_CHARS = 16000
ROUTE_MESSAGE_MAX_CHARS = 2000
PREPARE_ROUTE_SYSTEM_PROMPT = """You are a deterministic router for a penetration-testing agent graph.

Choose exactly one next action after context has been prepared and before the
main agent runs.

Allowed actions:
- information_collect: run the information collection subagent first, then continue to the main agent.
- execute_agent: skip pre-run information collection and run the main agent now.

Nodes can be selected more than once. Do not avoid an action only because its
node status is done or skipped. Decide from the current request, prepared
history, available context, and node visit counts.

Return only compact JSON in this exact shape:
{"next_action":"execute_agent"}"""
POST_EXECUTE_ROUTE_SYSTEM_PROMPT = """You are a deterministic router for a penetration-testing agent graph.

Choose exactly one next action after the main agent has produced a response.

Allowed actions:
- information_collect: run the information collection subagent, then return to the main agent.
- writeup: generate a final Markdown report from the available evidence.
- persist_output: finish this run and persist the current output.

Nodes can be selected more than once. Do not avoid an action only because its
node status is done or skipped. Decide from the latest request, evidence, node
visit counts, and generated messages.

Return only compact JSON in this exact shape:
{"next_action":"persist_output"}"""


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
        """Store run dependencies and compile the LangGraph workflow."""
        self.session_id = session_id
        self.input_text = input_text
        self.payload = payload
        self._messages = messages
        self._runtime = runtime
        self._rag_context = rag_context
        self._compiled_graph = self._build_execution_graph()

    def __getattr__(self, name: str) -> Any:
        """Forward unknown attributes to the compiled LangGraph object."""
        return getattr(self._compiled_graph, name)

    async def ainvoke(self, *args: Any, **kwargs: Any) -> Any:
        """Invoke the compiled graph asynchronously."""
        return await self._compiled_graph.ainvoke(*args, **kwargs)

    def _build_execution_graph(self) -> Any:
        """Compile the ordered graph nodes and conditional routing rules."""
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

    async def _route_after_prepare_context(self, state: AgentGraphState) -> str:
        """Use the LLM router to choose the first graph agent branch."""
        run = state["run"]
        decision = await self._llm_route_after_prepare_context(run)
        run.prepare_route_count += 1
        run.prepare_route_actions[decision] = (
            run.prepare_route_actions.get(decision, 0) + 1
        )
        if decision == "execute_agent":
            self._skip_pending_graph_node(run, "information_collect")
        return decision

    async def _llm_route_after_prepare_context(self, run: AgentRunContext) -> str:
        """Ask the main model to select the first graph agent branch."""
        try:
            result = await self._runtime.build_llm(MAIN_AGENT_NAME).ainvoke(
                [
                    SystemMessage(content=PREPARE_ROUTE_SYSTEM_PROMPT),
                    HumanMessage(content=self._prepare_route_context(run)),
                ]
            )
            decision = _parse_prepare_route(result)
            if decision:
                return decision
            logger.warning("Invalid prepare route decision: %s", result)
        except Exception as exc:
            logger.warning("Prepare LLM router failed: %s", exc)
        return self._fallback_prepare_route()

    def _fallback_prepare_route(self) -> str:
        """Conservative non-LLM fallback if prepare routing fails."""
        if should_collect_information(self.input_text):
            return "information_collect"
        return "execute_agent"

    def _prepare_route_context(self, run: AgentRunContext) -> str:
        """Build compact context for the pre-main-agent router."""
        payload = {
            "current_user_request": self.input_text,
            "available_actions": sorted(PREPARE_ROUTE_ACTIONS),
            "node_statuses": {
                node["id"]: node.get("status")
                for node in run.graph_nodes
                if node.get("id")
            },
            "node_visit_counts": run.node_visit_counts,
            "prepare_route_count": run.prepare_route_count,
            "prepare_route_actions": run.prepare_route_actions,
            "history_messages": _render_route_messages(run.history_messages),
            "has_mcp_tools": bool(run.mcp_tools),
            "system_prompt": run.full_system_prompt,
        }
        context = json.dumps(payload, ensure_ascii=False, default=str)
        if len(context) <= ROUTE_CONTEXT_MAX_CHARS:
            return context
        return (
            "The oldest prepare routing context was truncated.\n"
            + context[-ROUTE_CONTEXT_MAX_CHARS:]
        )

    async def _route_after_execute(self, state: AgentGraphState) -> str:
        """Use the LLM router to choose the next post-main-agent branch."""
        run = state["run"]
        decision = await self._llm_route_after_execute(run)
        decision = self._bounded_post_execute_route(run, decision)
        run.post_execute_route_count += 1
        run.post_execute_route_actions[decision] = (
            run.post_execute_route_actions.get(decision, 0) + 1
        )

        if decision == "persist_output":
            self._skip_pending_graph_node(run, "information_collect")
            self._skip_pending_graph_node(run, "writeup")
        elif decision == "writeup":
            self._skip_pending_graph_node(run, "information_collect")

        return decision

    async def _llm_route_after_execute(self, run: AgentRunContext) -> str:
        """Ask the main model to select the next graph action."""
        try:
            result = await self._runtime.build_llm(MAIN_AGENT_NAME).ainvoke(
                [
                    SystemMessage(content=POST_EXECUTE_ROUTE_SYSTEM_PROMPT),
                    HumanMessage(content=self._route_context(run)),
                ]
            )
            decision = _parse_post_execute_route(result)
            if decision:
                return decision
            logger.warning("Invalid post-execute route decision: %s", result)
        except Exception as exc:
            logger.warning("Post-execute LLM router failed: %s", exc)
        return self._fallback_post_execute_route(run)

    def _fallback_post_execute_route(self, run: AgentRunContext) -> str:
        """Conservative non-LLM fallback if routing fails."""
        if should_generate_writeup(self.input_text):
            return "writeup"
        if should_collect_information(self.input_text) and (
            run.post_execute_route_actions.get("information_collect", 0) == 0
        ):
            return "information_collect"
        return "persist_output"

    def _bounded_post_execute_route(
        self,
        run: AgentRunContext,
        decision: str,
    ) -> str:
        """Apply loop guards while still allowing repeated node visits."""
        if run.post_execute_route_count >= MAX_POST_EXECUTE_ROUTE_DECISIONS:
            logger.warning(
                "Post-execute route limit reached for session %s; persisting output",
                self.session_id,
            )
            return "persist_output"
        if (
            decision == "information_collect"
            and run.post_execute_route_actions.get("information_collect", 0)
            >= MAX_INFORMATION_COLLECT_ROUTES
        ):
            logger.warning(
                "Information collection route limit reached for session %s; "
                "persisting output",
                self.session_id,
            )
            return "persist_output"
        return decision

    def _route_context(self, run: AgentRunContext) -> str:
        """Build compact routing context for the LLM router."""
        payload = {
            "current_user_request": self.input_text,
            "available_actions": sorted(POST_EXECUTE_ROUTE_ACTIONS),
            "node_statuses": {
                node["id"]: node.get("status")
                for node in run.graph_nodes
                if node.get("id")
            },
            "node_visit_counts": run.node_visit_counts,
            "post_execute_route_count": run.post_execute_route_count,
            "post_execute_route_actions": run.post_execute_route_actions,
            "latest_information_collect_brief": run.information_collect_text,
            "latest_main_agent_messages": _render_route_messages(
                run.all_messages[len(run.history_messages) + 1 :]
            ),
            "generated_messages_so_far": _render_route_messages(
                run.generated_messages
            ),
        }
        context = json.dumps(payload, ensure_ascii=False, default=str)
        if len(context) <= ROUTE_CONTEXT_MAX_CHARS:
            return context
        return (
            "The oldest routing context was truncated.\n"
            + context[-ROUTE_CONTEXT_MAX_CHARS:]
        )

    async def _graph_persist_input(
        self,
        state: AgentGraphState,
    ) -> AgentGraphState:
        """Persist the user request and create the live assistant placeholder."""
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
        """Load tools, history, RAG context, and the effective system prompt."""
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
        """Generate and store a pre-run information collection brief."""
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
                run.information_collect_messages.append(collection_message)
                run.generated_messages.append(collection_message)
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
        """Run the main agent and tag any new AI messages it returns."""
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
            run.generated_messages.extend(
                run.all_messages[len(run.history_messages) + 1 :]
            )
        except Exception:
            await self._emit_graph_node(run, "execute_agent", "error")
            raise
        await self._emit_graph_node(run, "execute_agent", "done")
        return {"run": run}

    async def _graph_writeup(self, state: AgentGraphState) -> AgentGraphState:
        """Generate a report from accumulated messages and save it as an artifact."""
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
                    all_messages=_messages_for_writeup(run, self.input_text),
                    history_messages=run.history_messages,
                ),
                WRITEUP_AGENT_NAME,
            )
            run.writeup_text = extract_message_text(writeup_message)
            if run.writeup_text:
                save_writeup_artifact(self.session_id, run.writeup_text)
            run.all_messages.append(writeup_message)
            run.generated_messages.append(writeup_message)
        except Exception:
            await self._emit_graph_node(run, "writeup", "error")
            raise
        await self._emit_graph_node(run, "writeup", "done")
        return {"run": run}

    async def _graph_persist_output(
        self,
        state: AgentGraphState,
    ) -> AgentGraphState:
        """Persist final output, trace metadata, token usage, and done event."""
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
                for msg in run.generated_messages
            ]
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
        """Update graph status, persist trace metadata, and stream the event."""
        if status == "running":
            run.node_visit_counts[node_id] = run.node_visit_counts.get(node_id, 0) + 1
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
        """Queue a graph status event from synchronous routing callbacks."""
        self._set_graph_node_status(run, node_id, status)
        run.queue.put_nowait(self._graph_node_event(node_id, status))

    def _skip_pending_graph_node(self, run: AgentRunContext, node_id: str) -> None:
        """Mark an unvisited optional graph node as skipped."""
        for node in run.graph_nodes:
            if node["id"] == node_id:
                if node["status"] == "pending":
                    self._enqueue_graph_node(run, node_id, "skipped")
                return

    def _graph_node_event(self, node_id: str, status: str) -> AgentStreamEvent:
        """Build the stream event payload for a graph node status change."""
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
        """Mutate the run-local graph node status snapshot."""
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
        """Build the trace metadata stored on assistant messages."""
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
        """Write the current trace snapshot onto the assistant placeholder."""
        if run.assistant_msg_id is None:
            return
        await self._messages.persist_trace_metadata(
            assistant_msg_id=run.assistant_msg_id,
            metadata=self.run_metadata(run),
        )

    def agent_model_names(self) -> dict[str, str]:
        """Return resolved model names keyed by graph agent name."""
        return {
            INFORMATION_COLLECT_AGENT_NAME: self._runtime.agent_model_name(
                INFORMATION_COLLECT_AGENT_NAME
            ),
            MAIN_AGENT_NAME: self._runtime.agent_model_name(MAIN_AGENT_NAME),
            WRITEUP_AGENT_NAME: self._runtime.agent_model_name(WRITEUP_AGENT_NAME),
        }


def _messages_for_writeup(
    run: AgentRunContext,
    input_text: str,
) -> list[Any]:
    """Return all generated run messages in execution order for writeup."""
    return [
        *run.history_messages,
        HumanMessage(content=input_text),
        *run.generated_messages,
    ]


def _render_route_messages(
    messages: list[Any],
    *,
    max_messages: int = 12,
) -> list[dict[str, Any]]:
    """Render recent messages into compact JSON-safe routing context."""
    rendered: list[dict[str, Any]] = []
    for message in messages[-max_messages:]:
        content = extract_message_text(message)
        if not content and not isinstance(message, BaseMessage):
            content = str(message)
        if len(content) > ROUTE_MESSAGE_MAX_CHARS:
            content = content[:ROUTE_MESSAGE_MAX_CHARS] + "\n...[truncated]"

        tool_calls = getattr(message, "tool_calls", None)
        if tool_calls:
            tool_text = json.dumps(tool_calls, ensure_ascii=False, default=str)
            if len(tool_text) > ROUTE_MESSAGE_MAX_CHARS:
                tool_text = tool_text[:ROUTE_MESSAGE_MAX_CHARS] + "\n...[truncated]"
        else:
            tool_text = ""

        rendered.append(
            {
                "type": getattr(message, "type", type(message).__name__),
                "name": getattr(message, "name", None),
                "content": content,
                "tool_calls": tool_text,
            }
        )
    return rendered


def _parse_prepare_route(result: Any) -> str | None:
    """Parse an LLM prepare-route response into an allowed graph action."""
    text = extract_message_text(result).strip()
    if not text and isinstance(result, str):
        text = result.strip()
    if not text:
        return None

    parsed = _parse_route_json(text, PREPARE_ROUTE_ACTIONS)
    if parsed:
        return parsed

    normalized = text.strip().strip("`'\". ").lower()
    if normalized in PREPARE_ROUTE_ACTIONS:
        return normalized

    aliases = {
        "collect": "information_collect",
        "information": "information_collect",
        "information-collect": "information_collect",
        "recon": "information_collect",
        "execute": "execute_agent",
        "main": "execute_agent",
        "main_agent": "execute_agent",
        "run": "execute_agent",
        "continue": "execute_agent",
        "proceed": "execute_agent",
    }
    return aliases.get(normalized)


def _parse_post_execute_route(result: Any) -> str | None:
    """Parse an LLM routing response into an allowed graph action."""
    text = extract_message_text(result).strip()
    if not text and isinstance(result, str):
        text = result.strip()
    if not text:
        return None

    parsed = _parse_route_json(text, POST_EXECUTE_ROUTE_ACTIONS)
    if parsed:
        return parsed

    normalized = text.strip().strip("`'\". ").lower()
    if normalized in POST_EXECUTE_ROUTE_ACTIONS:
        return normalized

    aliases = {
        "collect": "information_collect",
        "information": "information_collect",
        "information-collect": "information_collect",
        "recon": "information_collect",
        "report": "writeup",
        "write-up": "writeup",
        "write up": "writeup",
        "finish": "persist_output",
        "final": "persist_output",
        "done": "persist_output",
        "persist": "persist_output",
    }
    return aliases.get(normalized)


def _parse_route_json(text: str, allowed_actions: set[str]) -> str | None:
    """Parse a JSON route response, including fenced JSON blocks."""
    candidate = text
    if "```" in candidate:
        parts = candidate.split("```")
        candidate = next(
            (
                part.removeprefix("json").strip()
                for part in parts
                if "next_action" in part or "action" in part
            ),
            candidate,
        )

    try:
        payload = json.loads(candidate)
    except json.JSONDecodeError:
        return None

    raw_action: Any
    if isinstance(payload, dict):
        raw_action = payload.get("next_action") or payload.get("action")
    else:
        raw_action = payload
    if not isinstance(raw_action, str):
        return None

    action = raw_action.strip().lower()
    return action if action in allowed_actions else None


def _append_information_collect_prompt(
    full_system_prompt: str,
    collection_markdown: str,
) -> str:
    """Append the collection brief to the main agent system prompt."""
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
    """Tag new AI messages with the graph agent that produced them."""
    for index in range(start_index, len(messages)):
        message = messages[index]
        if isinstance(message, AIMessage):
            messages[index] = _with_agent_name(message, name)


def _with_agent_name(message: AIMessage, name: str) -> AIMessage:
    """Return an AI message carrying the persisted graph agent name."""
    try:
        message.name = name
        return message
    except Exception:
        return message.model_copy(update={"name": name})
