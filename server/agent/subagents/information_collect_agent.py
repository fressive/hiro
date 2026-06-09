"""Information collection helpers for session-scoped agent runs."""

import json
import re
from datetime import datetime, timezone
from typing import Any, Callable

from deepagents import create_deep_agent
from langchain_core.messages import (
    AIMessage,
    BaseMessage,
    HumanMessage,
    ToolMessage,
)

from server.agent.runtime.context import SessionContext
from server.agent.subagents.base import SubAgent
from server.agent.tools.feroxbuster import feroxbuster
from server.agent.utils.tool_call_ids import (
    ToolCallIdMiddleware,
    normalize_model_messages,
)
from server.core.util import get_data_path


MAX_INFORMATION_CONTEXT_CHARS = 40000
MAX_EXISTING_INFO_CHARS = 20000
URL_PATTERN = re.compile(r"https?://[^\s<>'\"]+", re.IGNORECASE)
INFORMATION_COLLECT_INTENT_KEYWORDS = (
    "information collect",
    "collect information",
    "info collect",
    "recon",
    "reconnaissance",
    "enumerate",
    "fingerprint",
    "attack surface",
    "web information",
    "信息收集",
    "收集信息",
    "侦察",
    "枚举",
    "指纹",
    "探测",
)
INFORMATION_COLLECT_SYSTEM_PROMPT = """You are an information collection subagent.

Produce a concise Markdown collection brief for the main penetration-testing
agent before it starts deeper work.

Responsibilities:
- Identify the in-scope targets, URLs, hosts, and useful hints.
- Summarize relevant evidence already present in prior conversation or INFO.md.
- Propose concrete next collection steps, tools, and artifacts to update.
- Call out missing prerequisites or ambiguity that would affect collection.
- Use feroxbuster when authorized target URLs need web path discovery.
- Append concise useful collection notes and tool results to INFO.md in the
  working directory.

Rules:
- Do not claim that commands, scans, requests, or exploits were executed unless
  that evidence is present in the provided context.
- Keep findings clearly separated from next-step recommendations.
- Prefer actionable bullets over generic methodology.
- Treat feroxbuster output as evidence and include notable discovered paths,
  status codes, redirects, and errors.
- Return only Markdown, with no preamble."""
INFORMATION_COLLECT_AGENT_NAME = "information_collect_agent"


def extract_target_urls(input_text: str) -> list[str]:
    urls: list[str] = []
    for match in URL_PATTERN.finditer(input_text):
        url = match.group(0).rstrip(".,);]")
        if url not in urls:
            urls.append(url)
    return urls


def should_collect_information(input_text: str) -> bool:
    normalized = input_text.lower()
    return bool(extract_target_urls(input_text)) or any(
        keyword in normalized for keyword in INFORMATION_COLLECT_INTENT_KEYWORDS
    )


def read_information_collect_artifact(session_id: int) -> str:
    info_path = get_data_path(session_id) / "data" / "INFO.md"
    if not info_path.exists():
        return ""
    content = info_path.read_text(encoding="utf-8")
    if len(content) <= MAX_EXISTING_INFO_CHARS:
        return content
    return (
        "The oldest INFO.md content was truncated to fit the context window.\n\n"
        + content[-MAX_EXISTING_INFO_CHARS:]
    )


def append_information_collect_artifact(
    session_id: int,
    collection_markdown: str,
) -> None:
    content = collection_markdown.strip()
    if not content:
        return

    data_path = get_data_path(session_id) / "data"
    data_path.mkdir(parents=True, exist_ok=True)
    info_path = data_path / "INFO.md"
    timestamp = datetime.now(timezone.utc).isoformat()
    entry = f"\n\n## Information Collection - {timestamp}\n\n{content}\n"

    if info_path.exists() and info_path.stat().st_size > 0:
        with info_path.open("a", encoding="utf-8") as handle:
            handle.write(entry)
        return

    info_path.write_text(entry.lstrip(), encoding="utf-8")


class InformationCollectAgent(SubAgent):
    """Create a pre-run information collection brief for the main agent."""

    name = INFORMATION_COLLECT_AGENT_NAME
    description = (
        "Use proactively for target information collection, reconnaissance "
        "briefs, scope extraction, URL/host discovery, and collection plans "
        "before deeper penetration-testing work."
    )
    system_prompt = INFORMATION_COLLECT_SYSTEM_PROMPT
    skill_source_dir = "information-collect-agent"
    delegation_rule = (
        "For target information collection, reconnaissance briefs, scope "
        "extraction, URL/host discovery, or collection planning, call `task` "
        f"with `{INFORMATION_COLLECT_AGENT_NAME}` and include the target, "
        "scope, and known context."
    )
    order = 10

    @classmethod
    def tools(cls) -> list[Any]:
        return [feroxbuster]

    def __init__(
        self,
        *,
        session_id: int,
        input_text: str,
        build_llm: Callable[[], Any],
        callback: Any | None = None,
        skills: list[str] | None = None,
    ) -> None:
        self.session_id = session_id
        self.input_text = input_text
        self._build_llm = build_llm
        self.callback = callback
        self.tools = [feroxbuster]
        self.skill_sources = skills

    async def generate(
        self,
        *,
        history_messages: list[BaseMessage],
    ) -> AIMessage:
        collection_context = self.build_context(history_messages=history_messages)
        config = {"callbacks": [self.callback]} if self.callback is not None else None
        skill_sources = self.local_skill_sources(self.skill_sources)
        messages: list[BaseMessage] = [
            HumanMessage(content=collection_context),
        ]
        agent = create_deep_agent(
            model=self._build_llm(),
            tools=self.tools,
            system_prompt=INFORMATION_COLLECT_SYSTEM_PROMPT,
            middleware=[ToolCallIdMiddleware()],
            context_schema=SessionContext,
            name=INFORMATION_COLLECT_AGENT_NAME,
            skills=skill_sources or None,
            backend=self.local_skills_backend(skill_sources),
        )

        result_state = await agent.ainvoke(
            {"messages": messages},
            config=config,
            context=SessionContext(self.session_id),
        )
        result_messages = _state_messages(result_state)
        latest_ai_message = _last_ai_message(result_messages)
        if latest_ai_message is not None:
            return latest_ai_message

        return AIMessage(
            content="\n\n".join(
                _extract_message_text(message) for message in result_messages
            )
        )

    def build_context(
        self,
        *,
        history_messages: list[BaseMessage],
        existing_info: str | None = None,
    ) -> str:
        if existing_info is None:
            existing_info = read_information_collect_artifact(self.session_id)

        rendered_messages = [
            rendered
            for message in history_messages
            if (rendered := _format_message_for_information_collection(message))
        ]
        target_urls = extract_target_urls(self.input_text)

        context_parts = [
            f"Session ID: {self.session_id}",
            f"Generated at: {datetime.now(timezone.utc).isoformat()}",
            f"Current user request: {self.input_text}",
        ]
        if target_urls:
            context_parts.append(
                "Target URLs:\n"
                + "\n".join(f"- {url}" for url in target_urls)
            )
        if existing_info:
            context_parts.extend(["Existing INFO.md:", existing_info])
        if rendered_messages:
            context_parts.extend(
                [
                    "Prior conversation and evidence:",
                    *rendered_messages,
                ]
            )

        context = "\n\n".join(context_parts)
        if len(context) <= MAX_INFORMATION_CONTEXT_CHARS:
            return context
        return (
            "The oldest information collection context was truncated.\n\n"
            + context[-MAX_INFORMATION_CONTEXT_CHARS:]
        )


def _state_messages(result_state: Any) -> list[BaseMessage]:
    if isinstance(result_state, dict):
        result_messages = result_state.get("messages", [])
    else:
        result_messages = result_state
    if not isinstance(result_messages, list):
        result_messages = [result_messages]
    return normalize_model_messages(result_messages)


def _last_ai_message(messages: list[BaseMessage]) -> AIMessage | None:
    for message in reversed(messages):
        if isinstance(message, AIMessage):
            return message
    return None


def _format_message_for_information_collection(message: Any) -> str:
    label = _message_role_label(message)
    parts: list[str] = []
    content = _extract_message_text(message)
    if content:
        parts.append(content)

    tool_calls = getattr(message, "tool_calls", None)
    if tool_calls:
        parts.append(
            "Tool calls: "
            + json.dumps(tool_calls, ensure_ascii=True, default=str)
        )

    if not parts:
        return ""
    return f"### {label}\n" + "\n".join(parts)


def _message_role_label(message: Any) -> str:
    if isinstance(message, HumanMessage):
        return "User"
    if isinstance(message, AIMessage):
        return "Assistant"
    if isinstance(message, ToolMessage):
        name = getattr(message, "name", None) or "tool"
        return f"Tool: {name}"
    message_type = getattr(message, "type", None)
    if message_type:
        return str(message_type).title()
    return type(message).__name__


def _extract_message_text(message: Any) -> str:
    content = getattr(message, "content", None)
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return json.dumps(content, ensure_ascii=True, default=str)
    content_blocks = getattr(message, "content_blocks", None)
    if isinstance(content_blocks, list):
        return json.dumps(content_blocks, ensure_ascii=True, default=str)
    return ""
