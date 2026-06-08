"""Writeup generation helpers for session-scoped agent runs."""

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

from langchain_core.messages import (
    AIMessage,
    BaseMessage,
    HumanMessage,
    SystemMessage,
    ToolMessage,
)

from server.agent.utils.tool_call_ids import normalize_model_messages
from server.core.util import get_data_path


MAX_WRITEUP_CONTEXT_CHARS = 60000
WRITEUP_SKILLS_DIR = Path("./skills/writeup-agent")
WRITEUP_INTENT_KEYWORDS = (
    "writeup",
    "write up",
    "report",
    "pentest report",
    "summary",
    "总结",
    "报告",
    "复盘",
)
WRITEUP_SYSTEM_PROMPT = """You are a writeup subagent.

Generate a concise Markdown penetration-test report from the prior steps,
conversation, tool outputs, and final assistant result provided by the graph.

Requirements:
- Base the report only on provided evidence. Do not invent findings, flags, or exploitation results.
- Preserve important commands, URLs, payloads, tool outputs, and artifacts when they support a finding.
- If evidence is incomplete, say what is missing and mark the finding as unverified.
- Include these sections when applicable: Summary, Scope, Steps Performed, Findings, Evidence, Impact, Recommendations, Artifacts, and Next Steps.
- If a flag or proof value is present in the evidence, include it explicitly. If none is present, write "Flag: Not found".
- Return only the report Markdown, with no preamble."""
WRITEUP_AGENT_NAME = "writeup_agent"


def should_generate_writeup(input_text: str) -> bool:
    normalized = input_text.lower()
    return any(keyword in normalized for keyword in WRITEUP_INTENT_KEYWORDS)


def looks_like_writeup(content: str | None) -> bool:
    if not content:
        return False
    normalized = content.lower()
    return "# report" in normalized or "# writeup" in normalized or "## findings" in normalized


def save_writeup_artifact(session_id: int, report_markdown: str) -> None:
    data_path = get_data_path(session_id) / "data"
    data_path.mkdir(parents=True, exist_ok=True)
    (data_path / "WRITEUP.md").write_text(report_markdown, encoding="utf-8")


class WriteupAgent:
    """Generate a Markdown report from a completed agent run."""

    def __init__(
        self,
        *,
        session_id: int,
        input_text: str,
        build_llm: Callable[[], Any],
        callback: Any | None = None,
        skill_dirs: list[str] | None = None,
    ) -> None:
        self.session_id = session_id
        self.input_text = input_text
        self._build_llm = build_llm
        self.callback = callback
        self.skill_dirs = skill_dirs

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
        system_prompt = _append_workflow_skills(
            WRITEUP_SYSTEM_PROMPT,
            skill_dirs=self.skill_dirs,
        )
        result = await self._build_llm().ainvoke(
            [
                SystemMessage(content=system_prompt),
                HumanMessage(content=report_context),
            ],
            config=config,
        )
        result_messages = result if isinstance(result, list) else [result]
        normalized_messages = normalize_model_messages(result_messages)
        for message in reversed(normalized_messages):
            if isinstance(message, AIMessage):
                return message
        return AIMessage(
            content="\n\n".join(
                _extract_message_text(message) for message in result_messages
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
            if (rendered := _format_message_for_writeup(message))
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


def _append_workflow_skills(
    system_prompt: str,
    *,
    skill_dirs: list[str] | None,
) -> str:
    rendered_skills = []
    for skill_dir in _workflow_skill_dirs(skill_dirs):
        skill_path = skill_dir / "SKILL.md"
        content = skill_path.read_text(encoding="utf-8").strip()
        if not content:
            continue
        rendered_skills.append(
            f'<workflow_skill name="{skill_dir.name}" path="{skill_path.as_posix()}">\n'
            f"{content}\n"
            "</workflow_skill>"
        )

    if not rendered_skills:
        return system_prompt

    return (
        f"{system_prompt}\n\n"
        "## Workflow Skills\n\n"
        "Use these local project skills when they apply to this subagent's task.\n\n"
        + "\n\n".join(rendered_skills)
    )


def _workflow_skill_dirs(skill_dirs: list[str] | None) -> list[Path]:
    if skill_dirs is not None:
        paths = [Path(path) for path in skill_dirs]
        return [path for path in paths if (path / "SKILL.md").is_file()]
    if not WRITEUP_SKILLS_DIR.is_dir():
        return []
    return sorted(
        (
            child
            for child in WRITEUP_SKILLS_DIR.iterdir()
            if child.is_dir() and (child / "SKILL.md").is_file()
        ),
        key=lambda path: path.as_posix(),
    )


def _format_message_for_writeup(message: Any) -> str:
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
        return json.dumps(content)
    content_blocks = getattr(message, "content_blocks", None)
    if isinstance(content_blocks, list):
        return json.dumps(content_blocks)
    return ""
