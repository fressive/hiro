import asyncio

from langchain_core.messages import AIMessage

from server.agent.events.streaming import StreamCallbackHandler
from server.agent.runtime.agent_runtime import AgentRuntime
from server.models.llm import LLMConfig
from server.schemas.agent import AgentRunRequest


class FakeAsyncChannel:
    def __init__(self, items=()):
        self.items = list(items)

    def __aiter__(self):
        return self._iterate()

    async def _iterate(self):
        for item in self.items:
            await asyncio.sleep(0)
            yield item


class FakeMessageStream:
    def __init__(self, *, text=(), reasoning=(), output=None, usage=None):
        self.text = FakeAsyncChannel(text)
        self.reasoning = FakeAsyncChannel(reasoning)
        self._output = output or AIMessage(content="".join(text))
        if usage is not None:
            self._output.usage_metadata = usage

    async def output(self):
        await asyncio.sleep(0)
        return self._output


class FakeToolCallStream:
    def __init__(
        self,
        *,
        tool_call_id="call-1",
        tool_name="tool",
        input=None,
        output=None,
        error=None,
        output_deltas=(),
    ):
        self.tool_call_id = tool_call_id
        self.tool_name = tool_name
        self.input = input
        self.output = output
        self.error = error
        self.output_deltas = FakeAsyncChannel(output_deltas)


class FakeEventStream:
    def __init__(
        self,
        *,
        messages=(),
        tool_calls=(),
        subagents=(),
        output_state=None,
    ):
        self.messages = FakeAsyncChannel(messages)
        self.tool_calls = FakeAsyncChannel(tool_calls)
        self.subagents = FakeAsyncChannel(subagents)
        self.extensions = {
            "messages": self.messages,
            "tool_calls": self.tool_calls,
            "subagents": self.subagents,
        }
        self._output_state = output_state or {"messages": []}

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return None

    async def output(self):
        await asyncio.sleep(0)
        return self._output_state


class FakeSubagentStream(FakeEventStream):
    def __init__(
        self,
        *,
        name,
        path=("tools:1",),
        task_input=None,
        status="completed",
        error=None,
        **kwargs,
    ):
        super().__init__(**kwargs)
        self.name = name
        self.graph_name = name
        self.path = path
        self.task_input = task_input
        self.status = status
        self.error = error


async def _drain_stream_events(queue):
    await asyncio.sleep(0.01)
    events = []
    while not queue.empty():
        event = await queue.get()
        events.append((event.event, event.data))
    return events


def test_agent_runtime_registers_specialized_deepagent_subagents(monkeypatch):
    captured = {}
    build_llm_calls = []
    created_agents = []

    class FakeDeepAgent:
        def __init__(self):
            created_agents.append(self)
            self.invocations = []
            self.event_versions = []

        async def astream_events(self, state, version=None, context=None):
            captured["stream_state"] = state
            captured["stream_context"] = context
            self.event_versions.append(version)
            self.invocations.append(state)
            return FakeEventStream(
                output_state={
                    "messages": [*state["messages"], AIMessage(content="done")]
                }
            )

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
            full_system_prompt="Base prompt",
            run_context_prompt="",
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
    assert len(created_agents) == 1

    runtime.configure_run(
        input_text="second request",
        payload=AgentRunRequest(config_id=1, input="second request"),
        config=LLMConfig(provider="openai", api_key="test", model="test-model"),
    )
    second_result = asyncio.run(
        runtime.execute(
            history_messages=[],
            full_system_prompt="Updated prompt",
            run_context_prompt="",
            callback=None,
        )
    )

    assert second_result[-1].content == "done"
    assert len(created_agents) == 1
    assert created_agents[0].invocations[-1]["messages"][-1].content == (
        "second request"
    )
    assert created_agents[0].event_versions == ["v3", "v3"]
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
            created_agents.append(self)
            self.invocation_count = 0
            self.event_versions = []

        async def astream_events(self, state, version=None, context=None):
            self.invocation_count += 1
            self.event_versions.append(version)
            if self.invocation_count == 1:
                raise RuntimeError(
                    "Error code: 408 - stream error: stream disconnected "
                    "before completion: stream closed before response.completed"
                )
            return FakeEventStream(
                output_state={
                    "messages": [*state["messages"], AIMessage(content="done")]
                }
            )

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
            full_system_prompt="Base prompt",
            run_context_prompt="",
            callback=FakeCallback(),
        )
    )

    assert result[-1].content == "done"
    assert build_llm_calls == [
        ("main_agent", {"streaming": True}),
        ("information_collect_agent", {}),
        ("writeup_agent", {}),
    ]
    assert len(created_agents) == 1
    assert created_agents[0].invocation_count == 2
    assert created_agents[0].event_versions == ["v3", "v3"]
    assert ("rollback", 0) in events
    assert any(event == "live_rollback" for event, _ in events)
    assert any(event == "live_commit" for event, _ in events)


def test_agent_runtime_consumes_deepagent_event_stream(monkeypatch):
    captured = {}
    created_agents = []

    class FakeDeepAgent:
        async def astream_events(self, state, version=None, context=None):
            captured["version"] = version
            captured["context"] = context
            subagent = FakeSubagentStream(
                name="writeup_agent",
                task_input="draft report",
                messages=[
                    FakeMessageStream(
                        text=["sub"],
                        usage={
                            "input_tokens": 2,
                            "output_tokens": 1,
                            "total_tokens": 3,
                        },
                    )
                ],
                tool_calls=[
                    FakeToolCallStream(
                        tool_call_id="call-sub-tool",
                        tool_name="feroxbuster",
                        input={"url": "https://example.test"},
                        output="scan complete",
                    )
                ],
                output_state={"messages": [AIMessage(content="sub done")]},
            )
            return FakeEventStream(
                messages=[
                    FakeMessageStream(
                        text=["hel", "lo"],
                        usage={
                            "input_tokens": 3,
                            "output_tokens": 2,
                            "total_tokens": 5,
                        },
                    )
                ],
                tool_calls=[
                    FakeToolCallStream(
                        tool_call_id="call-mcp",
                        tool_name="mcp_call",
                        input={"tool_name": "lookup", "arguments": {"q": "x"}},
                        output={"ok": True},
                    )
                ],
                subagents=[subagent],
                output_state={
                    "messages": [*state["messages"], AIMessage(content="hello")]
                },
            )

    def fake_create_deep_agent(model, tools, **kwargs):
        created_agents.append((model, tools, kwargs))
        return FakeDeepAgent()

    payload = AgentRunRequest(config_id=1, input="scan target")
    runtime = AgentRuntime(
        session_id=123,
        input_text=payload.input,
        payload=payload,
        config=LLMConfig(provider="openai", api_key="test", model="test-model"),
    )

    monkeypatch.setattr(runtime, "build_llm", lambda *args, **kwargs: "model")
    monkeypatch.setattr(
        "server.agent.runtime.agent_runtime.create_deep_agent",
        fake_create_deep_agent,
    )

    async def run_test():
        queue = asyncio.Queue()
        callback = StreamCallbackHandler(queue, asyncio.get_running_loop())
        result = await runtime.execute(
            history_messages=[],
            full_system_prompt="Base prompt",
            run_context_prompt="",
            callback=callback,
        )
        events = await _drain_stream_events(queue)
        return result, callback, events

    result, callback, events = asyncio.run(run_test())

    event_names = [event for event, _ in events]
    assert result[-1].content == "hello"
    assert captured["version"] == "v3"
    assert captured["context"].session_id == 123
    assert callback.token_text == "hello"
    assert callback.usage == {
        "input_tokens": 5,
        "output_tokens": 3,
        "cached_input_tokens": 0,
    }
    assert callback.mcp_events[0]["name"] == "mcp_call"
    assert callback.tool_events[0]["name"] == "feroxbuster"
    assert callback.tool_events[0]["agent"] == "writeup_agent"
    assert callback.subagent_events == [
        {
            "id": "tools:1",
            "name": "writeup_agent",
            "path": "tools:1",
            "status": "done",
            "input": "draft report",
            "error": None,
        }
    ]
    assert "subagent_start" in event_names
    assert "subagent_end" in event_names
    assert "subagent_token" in event_names


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
