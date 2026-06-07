import asyncio

from langchain_core.messages import AIMessage

from server.agent.runtime.agent_runtime import AgentRuntime
from server.models.llm import LLMConfig
from server.schemas.agent import AgentRunRequest


def test_agent_runtime_informs_main_agent_about_workflow_subagents(monkeypatch):
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

    def fake_build_llm(agent_name=None):
        build_llm_calls.append(agent_name)
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
    assert result[-1].content == "done"
    assert "Workflow Subagent Delegation" in captured["system_prompt"]
    assert "The graph owns" in captured["system_prompt"]
    assert "specialized workflow subagents" in captured["system_prompt"]
    assert "`writeup_agent`" in captured["system_prompt"]
    assert "`information_collect_agent`" in captured["system_prompt"]
    assert "do not draft" in captured["system_prompt"]
    assert "Do not call the `task` tool with `writeup_agent`" in captured["system_prompt"]
    assert "writeup_agent" not in subagents
    assert "information_collect_agent" not in subagents
    assert "general-purpose" in subagents
    assert build_llm_calls == ["main_agent"]


def test_agent_runtime_disables_streaming_for_openai_compatible_base_url(monkeypatch):
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

    assert captured["streaming"] is False
    assert captured["disable_streaming"] is True
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
    assert "disable_streaming" not in captured
