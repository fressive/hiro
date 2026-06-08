from langchain_core.messages import AIMessage, HumanMessage, ToolMessage
import asyncio

from server.agent.subagents.writeup_agent import (
    WriteupAgent,
    looks_like_writeup,
    save_writeup_artifact,
    should_generate_writeup,
)


def test_should_generate_writeup_matches_report_intent():
    assert should_generate_writeup("please generate a pentest report")
    assert should_generate_writeup("请生成报告")
    assert not should_generate_writeup("continue scanning")


def test_looks_like_writeup_detects_report_markdown():
    assert looks_like_writeup("# Report\n\nSummary")
    assert looks_like_writeup("## Findings\n\n- Issue")
    assert not looks_like_writeup("plain assistant response")


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


def test_writeup_agent_includes_workflow_skill_prompt(tmp_path):
    skill_dir = tmp_path / "writeup"
    skill_dir.mkdir()
    (skill_dir / "SKILL.md").write_text(
        "---\n"
        "name: writeup\n"
        "description: Generate evidence-based reports.\n"
        "---\n\n"
        "Include reproduction steps and evidence.",
        encoding="utf-8",
    )
    captured = {}

    class FakeLLM:
        async def ainvoke(self, messages, config=None):
            captured["system_prompt"] = messages[0].content
            return AIMessage(content="# Report\n\nDone")

    agent = WriteupAgent(
        session_id=123,
        input_text="generate report",
        build_llm=lambda: FakeLLM(),
        skill_dirs=[str(skill_dir)],
    )

    result = asyncio.run(
        agent.generate(
            all_messages=[HumanMessage(content="found /admin")],
            history_messages=[],
        )
    )

    assert result.content == "# Report\n\nDone"
    assert "## Workflow Skills" in captured["system_prompt"]
    assert "writeup" in captured["system_prompt"]
    assert "Include reproduction steps and evidence." in captured["system_prompt"]


def test_save_writeup_artifact_writes_writeup_file(tmp_path, monkeypatch):
    monkeypatch.setattr(
        "server.agent.subagents.writeup_agent.get_data_path",
        lambda _: tmp_path,
    )

    save_writeup_artifact(123, "# Report\n\nDone")

    assert (tmp_path / "data" / "WRITEUP.md").read_text(encoding="utf-8") == (
        "# Report\n\nDone"
    )
