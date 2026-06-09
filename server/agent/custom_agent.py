"""Session-scoped agent runner with persistence and token accounting."""

import asyncio
from contextlib import suppress
from typing import Any, Callable

from langchain_core.messages import AIMessage, BaseMessage

from server.agent.events.streaming import (
    AgentStreamEvent,
    StreamCallbackHandler,
    stream_event,
)
from server.agent.persistence.message_store import AgentMessageStore
from server.agent.runtime.agent_runtime import AgentRuntime
from server.agent.runtime.run_context import AgentRunContext
from server.agent.utils.tool_call_ids import normalize_ai_message_tool_call_ids
from server.core.logger import logger
from server.models.llm import LLMConfig
from server.schemas.agent import AgentRunRequest
from server.service.rag_service import RagService

MAIN_AGENT_NAME = "main_agent"


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

    def configure_run(
        self,
        *,
        session_title: str | None,
        payload: AgentRunRequest,
        config: LLMConfig,
        agent_configs: dict[str, LLMConfig] | None = None,
    ) -> None:
        """Update run-specific settings while keeping this session agent."""

        self.session_title = session_title
        self.payload = payload
        self.config = config
        self.agent_configs = agent_configs or {}
        self.input_text = payload.input.strip()
        self.rag_context = ""
        self.rag_sources = []
        self._rag_loaded = False
        self._runtime.configure_run(
            input_text=self.input_text,
            payload=payload,
            config=config,
            agent_configs=self.agent_configs,
        )
        self._messages = AgentMessageStore(
            session_id=self.session_id,
            input_text=self.input_text,
            model=self.agent_model_names()[MAIN_AGENT_NAME],
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
            run_context = AgentRunContext(
                queue=queue,
                callback=callback,
                agent_done=asyncio.Event(),
            )
            await self._execute_run(run_context)

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
            if run_context is not None and run_context.exit_stack is not None:
                await run_context.exit_stack.aclose()
            if on_task_done:
                on_task_done()
            await queue.put(None)

    async def _execute_run(self, run: AgentRunContext) -> None:
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

        run.history_messages = await self._messages.load_history(
            user_msg_id=run.user_msg_id,
            assistant_msg_id=run.assistant_msg_id,
        )
        run.full_system_prompt = self._runtime.build_system_prompt()
        run.all_messages = await self._runtime.execute(
            history_messages=run.history_messages,
            full_system_prompt=run.full_system_prompt,
            run_context_prompt=self._runtime.build_run_context_prompt(
                rag_context=self.rag_context,
            ),
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

        run.agent_done.set()
        if run.update_task is not None:
            await run.update_task
            run.update_task = None

        if run.assistant_msg_id is None:
            raise RuntimeError("Assistant placeholder was not initialized")

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
            run_metadata=self.run_metadata(run),
            agent_models=self.agent_model_names(),
        )
        if not run.assistant_text:
            run.assistant_text = run.callback.token_text

        await run.queue.put(
            stream_event(
                "done",
                {"text": run.assistant_text, "session_id": self.session_id},
            )
        )

    def run_metadata(self, run: AgentRunContext) -> dict[str, Any]:
        return {
            "tool_events": run.callback.tool_events,
            "mcp_events": run.callback.mcp_events,
            "subagent_events": run.callback.subagent_events,
        }

    def agent_model_names(self) -> dict[str, str]:
        return self._runtime.agent_model_names()

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
