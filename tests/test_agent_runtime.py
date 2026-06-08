import asyncio

from langchain_core.messages import AIMessage

from server.agent.runtime.agent_runtime import AgentRuntime
from server.models.llm import LLMConfig
from server.schemas.agent import AgentRunRequest


def test_agent_runtime_registers_specialized_deepagent_subagents(monkeypatch):
    captured = {}
    build_llm_calls = []

    class FakeDeepAgent:
        async def ainvoke(self, state, config=None, context=None):
            captured["invoke_state"] = state
            return {"messages": [*state["messages"], AIMessage(content="done")]}

    def fake_create_deep_agent(model, tools, **kwargs):
        captured["model"] = model
        captured["tools"] = tools
        captured.update(kwargs)
        return FakeDeepAgent()

    payload = AgentRunRequest(config_id=1, input="generate a writeup")
    runtime = AgentRuntime(
        session_id=123,
        input_text=payload.input,
        payload=payload,
        config=LLMConfig(provider="openai", api_key="test", model="test-model"),
    )

    def fake_build_llm(agent_name=None, **kwargs):
        build_llm_calls.append((agent_name, kwargs))
        return f"model:{agent_name or 'default'}"

    monkeypatch.setattr(runtime, "build_llm", fake_build_llm)
    monkeypatch.setattr(
        "server.agent.runtime.agent_runtime.create_deep_agent",
        fake_create_deep_agent,
    )

    result = asyncio.run(
        runtime.execute(
            history_messages=[],
            mcp_tools=[],
            full_system_prompt="Base prompt",
            callback=None,
        )
    )

    subagents = {subagent["name"]: subagent for subagent in captured["subagents"]}
    permissions = captured["permissions"]
    assert result[-1].content == "done"
    assert "DeepAgent Subagent Delegation" in captured["system_prompt"]
    assert "Specialized DeepAgent subagents" in captured["system_prompt"]
    assert "`writeup_agent`" in captured["system_prompt"]
    assert "`information_collect_agent`" in captured["system_prompt"]
    assert "call `task`" in captured["system_prompt"]
    assert "general-purpose" in subagents
    assert "writeup_agent" in subagents
    assert "information_collect_agent" in subagents
    assert subagents["information_collect_agent"]["model"] == (
        "model:information_collect_agent"
    )
    assert subagents["information_collect_agent"]["tools"][0].name == "feroxbuster"
    assert subagents["writeup_agent"]["model"] == "model:writeup_agent"
    assert subagents["writeup_agent"]["tools"] == []
    assert permissions[0].mode == "deny"
    assert permissions[0].operations == ["write"]
    assert "/skills/**" in permissions[0].paths
    assert build_llm_calls == [
        ("main_agent", {"streaming": True}),
        ("information_collect_agent", {}),
        ("writeup_agent", {}),
    ]


def test_agent_runtime_retries_retryable_stream_errors(monkeypatch):
    events = []
    snapshots = []
    build_llm_calls = []

    class FakeCallback:
        def snapshot(self):
            snapshot = {"index": len(snapshots)}
            snapshots.append(snapshot)
            return snapshot

        def rollback(self, snapshot):
            events.append(("rollback", snapshot["index"]))

        def emit_event(self, event, data):
            events.append((event, data))

    class FakeDeepAgent:
        def __init__(self):
            self.index = len(created_agents)
            created_agents.append(self)

        async def ainvoke(self, state, config=None, context=None):
            if self.index == 0:
                raise RuntimeError(
                    "Error code: 408 - stream error: stream disconnected "
                    "before completion: stream closed before response.completed"
                )
            return {"messages": [*state["messages"], AIMessage(content="done")]}

    def fake_create_deep_agent(model, tools, **kwargs):
        return FakeDeepAgent()

    created_agents = []
    payload = AgentRunRequest(config_id=1, input="scan target")
    runtime = AgentRuntime(
        session_id=123,
        input_text=payload.input,
        payload=payload,
        config=LLMConfig(provider="openai", api_key="test", model="test-model"),
    )

    def fake_build_llm(agent_name=None, **kwargs):
        build_llm_calls.append((agent_name, kwargs))
        return f"model:{agent_name or 'default'}:{kwargs.get('streaming')}"

    monkeypatch.setattr(runtime, "build_llm", fake_build_llm)
    monkeypatch.setattr(
        "server.agent.runtime.agent_runtime.create_deep_agent",
        fake_create_deep_agent,
    )
    monkeypatch.setattr(
        "server.agent.runtime.agent_runtime.STREAM_RETRY_BACKOFF_SECONDS",
        0,
    )

    result = asyncio.run(
        runtime.execute(
            history_messages=[],
            mcp_tools=[],
            full_system_prompt="Base prompt",
            callback=FakeCallback(),
        )
    )

    assert result[-1].content == "done"
    assert build_llm_calls == [
        ("main_agent", {"streaming": True}),
        ("information_collect_agent", {}),
        ("writeup_agent", {}),
        ("main_agent", {"streaming": True}),
        ("information_collect_agent", {}),
        ("writeup_agent", {}),
    ]
    assert ("rollback", 0) in events
    assert any(event == "live_rollback" for event, _ in events)
    assert any(event == "live_commit" for event, _ in events)


def test_agent_runtime_keeps_streaming_for_openai_compatible_base_url(monkeypatch):
    captured = {}
    payload = AgentRunRequest(config_id=1, input="scan target")
    runtime = AgentRuntime(
        session_id=123,
        input_text=payload.input,
        payload=payload,
        config=LLMConfig(
            provider="openai",
            api_key="test",
            model="test-model",
            base_url="https://proxy.example/v1",
        ),
    )

    def fake_init_chat_model(**kwargs):
        captured.update(kwargs)
        return object()

    monkeypatch.setattr(
        "server.agent.runtime.agent_runtime.init_chat_model",
        fake_init_chat_model,
    )

    runtime.build_llm("main_agent")

    assert captured["streaming"] is True
    assert captured["stream_usage"] is False
    assert captured["base_url"] == "https://proxy.example/v1"


def test_agent_runtime_keeps_streaming_for_native_openai(monkeypatch):
    captured = {}
    payload = AgentRunRequest(config_id=1, input="scan target")
    runtime = AgentRuntime(
        session_id=123,
        input_text=payload.input,
        payload=payload,
        config=LLMConfig(provider="openai", api_key="test", model="test-model"),
    )

    def fake_init_chat_model(**kwargs):
        captured.update(kwargs)
        return object()

    monkeypatch.setattr(
        "server.agent.runtime.agent_runtime.init_chat_model",
        fake_init_chat_model,
    )

    runtime.build_llm("main_agent")

    assert captured["streaming"] is True
    assert "stream_usage" not in captured
