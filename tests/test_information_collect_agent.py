import asyncio

from langchain_core.messages import AIMessage, HumanMessage, ToolMessage

from server.agent.subagents.information_collect_agent import (
    InformationCollectAgent,
    append_information_collect_artifact,
    extract_target_urls,
    should_collect_information,
)
from server.agent.tools.feroxbuster import run_feroxbuster_scan


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


def test_information_collect_agent_uses_feroxbuster_tool(monkeypatch):
    class FakeLLM:
        def __init__(self):
            self.bound_tools = []
            self.calls = []

        def bind_tools(self, tools):
            self.bound_tools = tools
            return self

        async def ainvoke(self, messages, config=None):
            self.calls.append(messages)
            if len(self.calls) == 1:
                assert any(tool.name == "feroxbuster" for tool in self.bound_tools)
                return AIMessage(
                    content="",
                    tool_calls=[
                        {
                            "name": "feroxbuster",
                            "args": {"target_url": "https://target.test"},
                            "id": "call-ferox",
                            "type": "tool_call",
                        }
                    ],
                )

            assert any(
                isinstance(message, ToolMessage)
                and message.name == "feroxbuster"
                and "200 /admin" in message.content
                for message in messages
            )
            return AIMessage(content="## Findings\n- Feroxbuster found /admin")

    fake_llm = FakeLLM()
    scan_calls = []

    def fake_scan(**kwargs):
        scan_calls.append(kwargs)
        return "200 /admin"

    monkeypatch.setattr(
        "server.agent.tools.feroxbuster.run_feroxbuster_scan",
        fake_scan,
    )

    agent = InformationCollectAgent(
        session_id=123,
        input_text="collect information for https://target.test",
        build_llm=lambda: fake_llm,
    )

    result = asyncio.run(agent.generate(history_messages=[]))

    assert result.content == "## Findings\n- Feroxbuster found /admin"
    assert scan_calls == [
        {
            "session_id": 123,
            "target_url": "https://target.test",
            "wordlist": None,
            "extensions": None,
            "depth": 2,
            "threads": 10,
            "timeout_seconds": 120,
            "follow_redirects": True,
            "insecure": True,
        }
    ]


def test_run_feroxbuster_scan_builds_sandboxed_command(monkeypatch, tmp_path):
    calls = []

    def fake_run_command(command, session_id, timeout=None, cwd=None):
        calls.append(
            {
                "command": command,
                "session_id": session_id,
                "timeout": timeout,
                "cwd": cwd,
            }
        )
        return "200 /admin"

    monkeypatch.setattr(
        "server.agent.tools.feroxbuster.get_data_path",
        lambda session_id: tmp_path / str(session_id),
    )
    monkeypatch.setattr(
        "server.agent.tools.feroxbuster.run_command",
        fake_run_command,
    )

    result = run_feroxbuster_scan(
        session_id=123,
        target_url="https://target.test",
        extensions="php, txt",
        depth=3,
        threads=8,
        timeout_seconds=30,
    )

    assert result == "200 /admin"
    assert calls == [
        {
            "command": [
                "feroxbuster",
                "-u",
                "https://target.test",
                "--no-state",
                "--silent",
                "--depth",
                "3",
                "--threads",
                "8",
                "--redirects",
                "--insecure",
                "--extensions",
                "php,txt",
            ],
            "session_id": 123,
            "timeout": 30,
            "cwd": tmp_path / "123",
        }
    ]


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
