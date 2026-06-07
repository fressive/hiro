from langchain_core.messages import AIMessage, HumanMessage, ToolMessage

from server.agent.writeup_agent import (
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


def test_save_writeup_artifact_writes_writeup_file(tmp_path, monkeypatch):
    monkeypatch.setattr("server.agent.writeup_agent.get_data_path", lambda _: tmp_path)

    save_writeup_artifact(123, "# Report\n\nDone")

    assert (tmp_path / "data" / "WRITEUP.md").read_text(encoding="utf-8") == (
        "# Report\n\nDone"
    )
