import asyncio
from typing import Any

from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import AIMessage, BaseMessage, HumanMessage, ToolMessage
from langchain_core.outputs import ChatGeneration, ChatResult
from pydantic import Field

from server.agent.subagents.writeup_agent import WriteupAgent

class FakeChatModel(BaseChatModel):
    response: BaseMessage
    calls: list[list[BaseMessage]] = Field(default_factory=list)
    bound_tools: list[Any] = Field(default_factory=list)

    def bind_tools(self, tools, *, tool_choice=None, **kwargs):
        self.bound_tools = list(tools)
        return self

    def _generate(self, messages, stop=None, run_manager=None, **kwargs):
        raise AssertionError("sync generation should not be used")

    async def _agenerate(self, messages, stop=None, run_manager=None, **kwargs):
        self.calls.append(messages)
        return ChatResult(generations=[ChatGeneration(message=self.response)])

    @property
    def _llm_type(self):
        return "fake-chat-model"


def _message_text(message: BaseMessage) -> str:
    content = message.content
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return "\n".join(
            block.get("text", str(block)) if isinstance(block, dict) else str(block)
            for block in content
        )
    return str(content)


def test_writeup_agent_builds_context_from_run_messages():
    agent = WriteupAgent(
        session_id=123,
        input_text="generate report",
        build_llm=lambda: None,
    )

    context = agent.build_context(
        all_messages=[
            HumanMessage(content="scan target"),
            AIMessage(
                content="found /admin",
                tool_calls=[
                    {
                        "name": "curl",
                        "args": {"url": "https://target/admin"},
                        "id": "call-1",
                    }
                ],
            ),
            ToolMessage(
                content="HTTP 200",
                tool_call_id="call-1",
                name="curl",
            ),
        ],
        history_messages=[],
    )

    assert "Session ID: 123" in context
    assert "Current user request: generate report" in context
    assert "### User\nscan target" in context
    assert "### Assistant\nfound /admin" in context
    assert "Tool calls:" in context
    assert "### Tool: curl\nHTTP 200" in context


def test_writeup_agent_passes_skill_sources_to_deepagent(tmp_path):
    skills_root = tmp_path / "writeup-agent"
    skill_dir = skills_root / "writeup"
    skill_dir.mkdir(parents=True)
    (skill_dir / "SKILL.md").write_text(
        "---\n"
        "name: writeup\n"
        "description: Generate evidence-based reports.\n"
        "---\n\n"
        "Include reproduction steps and evidence.",
        encoding="utf-8",
    )
    fake_llm = FakeChatModel(response=AIMessage(content="# Report\n\nDone"))

    agent = WriteupAgent(
        session_id=123,
        input_text="generate report",
        build_llm=lambda: fake_llm,
        skills=[str(skills_root)],
    )

    result = asyncio.run(
        agent.generate(
            all_messages=[HumanMessage(content="found /admin")],
            history_messages=[],
        )
    )

    system_prompt = _message_text(fake_llm.calls[0][0])
    assert result.content == "# Report\n\nDone"
    assert "writeup" in system_prompt
    assert "Generate evidence-based reports." in system_prompt
    assert f"{skill_dir.as_posix()}/SKILL.md" in system_prompt