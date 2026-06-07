from langchain_core.messages import AIMessage, HumanMessage, ToolMessage

from server.agent.subagents.information_collect_agent import (
    InformationCollectAgent,
    append_information_collect_artifact,
    extract_target_urls,
    should_collect_information,
)


def test_should_collect_information_matches_target_or_intent():
    assert should_collect_information("collect information for https://target.test")
    assert should_collect_information("请对这个站点做信息收集")
    assert should_collect_information("run recon on target.test")
    assert not should_collect_information("continue exploitation from the prior step")


def test_extract_target_urls_deduplicates_and_trims_punctuation():
    assert extract_target_urls(
        "check https://target.test/admin, then https://target.test/admin."
    ) == ["https://target.test/admin"]


def test_information_collect_agent_builds_context_from_history_and_info():
    agent = InformationCollectAgent(
        session_id=123,
        input_text="collect information for https://target.test",
        build_llm=lambda: None,
    )

    context = agent.build_context(
        history_messages=[
            HumanMessage(content="previous note"),
            AIMessage(
                content="found /admin",
                tool_calls=[
                    {
                        "name": "curl",
                        "args": {"url": "https://target.test/admin"},
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
        existing_info="dirsearch result saved to data/dirsearch.csv",
    )

    assert "Session ID: 123" in context
    assert "Current user request: collect information for https://target.test" in context
    assert "Target URLs:\n- https://target.test" in context
    assert "Existing INFO.md:" in context
    assert "dirsearch result saved to data/dirsearch.csv" in context
    assert "### User\nprevious note" in context
    assert "### Assistant\nfound /admin" in context
    assert "Tool calls:" in context
    assert "### Tool: curl\nHTTP 200" in context


def test_append_information_collect_artifact_appends_info_file(tmp_path, monkeypatch):
    monkeypatch.setattr(
        "server.agent.subagents.information_collect_agent.get_data_path",
        lambda _: tmp_path,
    )

    append_information_collect_artifact(123, "First brief")
    append_information_collect_artifact(123, "Second brief")

    content = (tmp_path / "data" / "INFO.md").read_text(encoding="utf-8")
    assert "## Information Collection -" in content
    assert "First brief" in content
    assert "Second brief" in content
