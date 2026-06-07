"""Session message persistence and history reconstruction."""

import asyncio
import json
from datetime import datetime, timezone
from typing import Any, Callable

from langchain_core.messages import AIMessage, BaseMessage, HumanMessage, ToolMessage
from sqlalchemy import select

from server.agent import token_usage
from server.agent.streaming import StreamCallbackHandler
from server.agent.tool_call_ids import (
    is_valid_tool_call_id,
    normalize_ai_message_tool_call_ids,
)
from server.core.logger import logger
from server.db import AsyncSessionLocal
from server.models.models import AgentMessage, AgentSession


def extract_message_text(message: Any) -> str:
    content = getattr(message, "content", None)
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return json.dumps(content)
    content_blocks = getattr(message, "content_blocks", None)
    if isinstance(content_blocks, list):
        return json.dumps(content_blocks)
    return ""


class AgentMessageStore:
    def __init__(self, *, session_id: int, input_text: str, model: str) -> None:
        self.session_id = session_id
        self.input_text = input_text
        self.model = model

    async def save_user_message(self) -> int:
        async with AsyncSessionLocal() as db_session:
            user_message = AgentMessage(
                session_id=self.session_id,
                role="user",
                content=self.input_text,
                created_at=datetime.now(timezone.utc),
            )
            db_session.add(user_message)

            sess_result = await db_session.execute(
                select(AgentSession).where(AgentSession.id == self.session_id)
            )
            db_sess = sess_result.scalars().first()
            if db_sess:
                db_sess.updated_at = datetime.now(timezone.utc)
                if not db_sess.title:
                    db_sess.title = self.input_text[:80]

            await db_session.commit()
            await db_session.refresh(user_message)
            return user_message.id

    async def create_assistant_placeholder(self) -> int:
        async with AsyncSessionLocal() as db_session:
            assistant_message = AgentMessage(
                session_id=self.session_id,
                role="assistant",
                content="",
                model=self.model,
                created_at=datetime.now(timezone.utc),
            )
            db_session.add(assistant_message)
            await db_session.commit()
            await db_session.refresh(assistant_message)
            return assistant_message.id

    async def update_assistant_periodically(
        self,
        assistant_msg_id: int,
        callback: StreamCallbackHandler,
        agent_done: asyncio.Event,
        metadata_provider: Callable[[], dict[str, Any]] | None = None,
    ) -> None:
        last_saved = ""
        last_metadata = ""
        while not agent_done.is_set():
            try:
                await asyncio.wait_for(agent_done.wait(), timeout=2)
                break
            except asyncio.TimeoutError:
                current = callback.token_text
                metadata = metadata_provider() if metadata_provider else None
                metadata_key = json.dumps(metadata, sort_keys=True, default=str)
                if current == last_saved and metadata_key == last_metadata:
                    continue
                async with AsyncSessionLocal() as db_session:
                    msg = await db_session.get(AgentMessage, assistant_msg_id)
                    if msg:
                        msg.content = current
                        if metadata is not None:
                            msg.extra_metadata = metadata
                        await db_session.commit()
                        last_saved = current
                        last_metadata = metadata_key
            except Exception as exc:
                logger.error("Error in periodic assistant update: %s", exc)

    async def load_history(
        self, *, user_msg_id: int, assistant_msg_id: int
    ) -> list[BaseMessage]:
        history_messages: list[BaseMessage] = []
        pending_tool_calls: list[dict[str, str | None]] = []

        async with AsyncSessionLocal() as db_session:
            result = await db_session.execute(
                select(AgentMessage)
                .where(AgentMessage.session_id == self.session_id)
                .order_by(AgentMessage.created_at.asc())
            )
            db_messages = result.scalars().all()

        for message in db_messages:
            if message.id in {user_msg_id, assistant_msg_id}:
                continue

            if message.role == "assistant":
                if not message.content and not message.tool_calls:
                    continue
                ai_message = normalize_ai_message_tool_call_ids(
                    AIMessage(
                        content=message.content,
                        tool_calls=message.tool_calls or [],
                    )
                )
                history_messages.append(ai_message)
                for tool_call in getattr(ai_message, "tool_calls", []):
                    tool_call_id = tool_call.get("id")
                    if is_valid_tool_call_id(tool_call_id):
                        pending_tool_calls.append(
                            {"id": tool_call_id, "name": tool_call.get("name")}
                        )
            elif message.role == "tool":
                tool_message = self._build_history_tool_message(
                    message, pending_tool_calls
                )
                if tool_message:
                    history_messages.append(tool_message)
            else:
                history_messages.append(HumanMessage(content=message.content))

        for tool_call in pending_tool_calls:
            history_messages.append(
                ToolMessage(
                    content=(
                        "Tool call "
                        f"{tool_call['name'] or 'unknown'} was cancelled before "
                        "a result was saved."
                    ),
                    tool_call_id=tool_call["id"],
                    name=tool_call["name"],
                    status="error",
                )
            )

        return history_messages

    def _build_history_tool_message(
        self,
        message: AgentMessage,
        pending_tool_calls: list[dict[str, str | None]],
    ) -> ToolMessage | None:
        tcid = message.tool_call_id
        if not is_valid_tool_call_id(tcid):
            matching_indexes = [
                index
                for index, tool_call in enumerate(pending_tool_calls)
                if tool_call["name"] == message.name
            ]
            if len(matching_indexes) == 1:
                tcid = pending_tool_calls.pop(matching_indexes[0])["id"]
            elif len(pending_tool_calls) == 1:
                tcid = pending_tool_calls.pop(0)["id"]
            else:
                logger.warning(
                    "Skipping tool message %s with missing tool_call_id",
                    message.id,
                )
                return None
        else:
            matching_index = next(
                (
                    index
                    for index, tool_call in enumerate(pending_tool_calls)
                    if tool_call["id"] == tcid
                ),
                None,
            )
            if matching_index is None:
                logger.warning(
                    "Skipping orphan tool message %s with tool_call_id %s",
                    message.id,
                    tcid,
                )
                return None
            pending_tool_calls.pop(matching_index)

        return ToolMessage(
            content=message.content,
            tool_call_id=tcid,
            name=message.name,
        )

    async def persist_trace_metadata(
        self, *, assistant_msg_id: int, metadata: dict[str, Any]
    ) -> None:
        async with AsyncSessionLocal() as db_session:
            msg = await db_session.get(AgentMessage, assistant_msg_id)
            if msg:
                msg.extra_metadata = metadata
                await db_session.commit()

    async def save_final_messages(
        self,
        *,
        new_messages: list[Any],
        assistant_msg_id: int,
        callback_usage: Any,
        callback_text: str,
        run_metadata: dict[str, Any] | None = None,
    ) -> str:
        assistant_text = ""
        message_usages = {
            index: token_usage.message_token_usage(msg)
            for index, msg in enumerate(new_messages)
            if isinstance(msg, AIMessage)
        }
        normalized_callback_usage = token_usage.normalize_token_usage(callback_usage)
        residual_usage = token_usage.subtract_token_usage(
            normalized_callback_usage,
            token_usage.add_token_usage(*message_usages.values()),
        )
        residual_applied = False
        placeholder_updated = False
        trace_message: AgentMessage | None = None
        fallback_trace_message: AgentMessage | None = None

        async with AsyncSessionLocal() as db_session:
            for index, msg in enumerate(new_messages):
                role = "user"
                content = extract_message_text(msg)
                usage = token_usage.empty_token_usage()

                if isinstance(msg, AIMessage):
                    role = "assistant"
                    if not assistant_text and not msg.tool_calls:
                        assistant_text = content

                    usage = message_usages.get(index, token_usage.empty_token_usage())
                    if not residual_applied and token_usage.has_token_usage(
                        residual_usage
                    ):
                        usage = token_usage.add_token_usage(usage, residual_usage)
                        residual_applied = True

                    if not placeholder_updated:
                        msg_to_update = await db_session.get(
                            AgentMessage, assistant_msg_id
                        )
                        if msg_to_update:
                            msg_to_update.content = content
                            msg_to_update.tool_calls = msg.tool_calls
                            msg_to_update.model = self.model
                            if run_metadata is not None:
                                if content and not msg.tool_calls:
                                    trace_message = msg_to_update
                                else:
                                    fallback_trace_message = msg_to_update
                            token_usage.apply_token_usage(msg_to_update, usage)
                            placeholder_updated = True
                            continue

                elif isinstance(msg, ToolMessage):
                    role = "tool"
                elif isinstance(msg, HumanMessage):
                    role = "user"

                db_msg = AgentMessage(
                    session_id=self.session_id,
                    role=role,
                    content=content,
                    name=getattr(msg, "name", None),
                    tool_call_id=getattr(msg, "tool_call_id", None),
                    tool_calls=getattr(msg, "tool_calls", None),
                    model=self.model if role == "assistant" else None,
                    created_at=datetime.now(timezone.utc),
                )

                if isinstance(msg, AIMessage):
                    token_usage.apply_token_usage(db_msg, usage)
                    if run_metadata is not None:
                        if content and not msg.tool_calls:
                            trace_message = db_msg
                        elif fallback_trace_message is None:
                            fallback_trace_message = db_msg

                db_session.add(db_msg)

            if not placeholder_updated and (
                callback_text
                or token_usage.has_token_usage(normalized_callback_usage)
                or run_metadata
            ):
                msg_to_update = await db_session.get(AgentMessage, assistant_msg_id)
                if msg_to_update:
                    msg_to_update.content = callback_text
                    msg_to_update.model = self.model
                    if run_metadata is not None:
                        trace_message = msg_to_update
                    token_usage.apply_token_usage(
                        msg_to_update, normalized_callback_usage
                    )

            if run_metadata is not None:
                target = trace_message or fallback_trace_message
                if target is not None:
                    target.extra_metadata = run_metadata
                if (
                    fallback_trace_message is not None
                    and trace_message is not None
                    and fallback_trace_message is not trace_message
                ):
                    fallback_trace_message.extra_metadata = None

            await db_session.commit()

        return assistant_text

    async def write_error_message(
        self, exc: Exception, assistant_msg_id: int | None
    ) -> None:
        async with AsyncSessionLocal() as db_session:
            if assistant_msg_id is not None:
                msg = await db_session.get(AgentMessage, assistant_msg_id)
                if msg:
                    msg.content = f"Error: {exc}"
                    msg.model = self.model
                    await db_session.commit()
                    return

            db_session.add(
                AgentMessage(
                    session_id=self.session_id,
                    role="assistant",
                    content=f"Error: {exc}",
                    model=self.model,
                    created_at=datetime.now(timezone.utc),
                )
            )
            await db_session.commit()
