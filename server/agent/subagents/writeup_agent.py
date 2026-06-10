"""Writeup generation helpers for session-scoped agent runs."""

from datetime import datetime, timezone
from typing import Any, Callable

from deepagents import create_deep_agent
from langchain_core.messages import (
    AIMessage,
    BaseMessage,
    HumanMessage,
)

from server.agent.runtime.context import SessionContext
from server.agent.subagents.base import SubAgent
from server.agent.utils.tool_call_ids import (
    ToolCallIdMiddleware,
)
from server.agent.utils.messages import (
    extract_message_text,
    format_message_for_context,
    last_ai_message,
    normalize_result_messages,
)
from server.core.util import get_data_path

MAX_WRITEUP_CONTEXT_CHARS = 60000

WRITEUP_SYSTEM_PROMPT = """You are a writeup subagent.

Generate a concise Markdown penetration-test report from the prior steps,
conversation, tool outputs, and final assistant result provided by the calling
agent.

Requirements:
- Base the report only on provided evidence. Do not invent findings, flags, or exploitation results.
- Preserve important commands, URLs, payloads, tool outputs, and artifacts when they support a finding.
- If evidence is incomplete, say what is missing and mark the finding as unverified.
- Include these sections when applicable: Summary, Scope, Steps Performed, Findings, Evidence, Impact, Recommendations, Artifacts, and Next Steps.
- If a flag or proof value is present in the evidence, include it explicitly. If none is present, write "Flag: Not found".
- Save the final report to WRITEUP.md in the working directory.
- Return only the report Markdown, with no preamble."""
WRITEUP_AGENT_NAME = "writeup_agent"

class WriteupAgent(SubAgent):
    """Generate a Markdown report from a completed agent run."""

    name = WRITEUP_AGENT_NAME
    description = (
        "Use for writeups, reports, summaries, and final Markdown reporting "
        "from prior conversation, tool output, evidence, and artifacts."
    )
    system_prompt = WRITEUP_SYSTEM_PROMPT
    skill_source_dir = "writeup-agent"
    delegation_rule = (
        "For writeups, reports, summaries, or final Markdown reporting, call "
        f"`task` with `{WRITEUP_AGENT_NAME}` and include the relevant evidence, "
        "commands, findings, and artifacts."
    )
    order = 20

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
        self.skill_sources = skills

    async def generate(
        self,
        *,
        all_messages: list[Any],
        history_messages: list[BaseMessage],
    ) -> AIMessage:
        report_context = self.build_context(
            all_messages=all_messages,
            history_messages=history_messages,
        )
        config = {"callbacks": [self.callback]} if self.callback is not None else None
        skill_sources = self.local_skill_sources(self.skill_sources)
        agent = create_deep_agent(
            model=self._build_llm(),
            tools=[],
            system_prompt=WRITEUP_SYSTEM_PROMPT,
            middleware=[ToolCallIdMiddleware()],
            context_schema=SessionContext,
            name=WRITEUP_AGENT_NAME,
            skills=skill_sources or None,
            backend=self.local_skills_backend(skill_sources),
        )
        result_state = await agent.ainvoke(
            {"messages": [HumanMessage(content=report_context)]},
            config=config,
            context=SessionContext(self.session_id),
        )
        normalized_messages = normalize_result_messages(result_state)
        latest_ai_message = last_ai_message(normalized_messages)
        if latest_ai_message is not None:
            return latest_ai_message
        return AIMessage(
            content="\n\n".join(
                extract_message_text(message) for message in normalized_messages
            )
        )

    def build_context(
        self,
        *,
        all_messages: list[Any],
        history_messages: list[BaseMessage],
    ) -> str:
        messages = all_messages or (
            history_messages + [HumanMessage(content=self.input_text)]
        )
        rendered_messages = [
            rendered
            for message in messages
            if (rendered := format_message_for_context(message))
        ]
        context = "\n\n".join(
            [
                f"Session ID: {self.session_id}",
                f"Generated at: {datetime.now(timezone.utc).isoformat()}",
                f"Current user request: {self.input_text}",
                "Prior steps, tool outputs, and assistant results:",
                *rendered_messages,
            ]
        )
        if len(context) <= MAX_WRITEUP_CONTEXT_CHARS:
            return context
        return (
            "The oldest context was truncated to fit the writeup window.\n\n"
            + context[-MAX_WRITEUP_CONTEXT_CHARS:]
        )
