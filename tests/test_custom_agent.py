import asyncio

from langchain_core.messages import AIMessage, HumanMessage

from server.agent.custom_agent import CustomAgent
from server.agent.events.streaming import AgentStreamEvent, StreamCallbackHandler
from server.api.v1.endpoints import session as session_endpoint
from server.models.agent import AgentSession
from server.models.llm import LLMConfig
from server.schemas.agent import AgentRunRequest


def _parse_stream_event(raw_event: AgentStreamEvent):
    return raw_event.event, raw_event.data


async def _collect_until_closed(queue: asyncio.Queue[AgentStreamEvent | None]):
    events = []
    while True:
        raw_event = await queue.get()
        if raw_event is None:
            return events
        events.append(_parse_stream_event(raw_event))


def test_custom_agent_persists_done_event(monkeypatch):
    async def run_agent():
        payload = AgentRunRequest(config_id=1, input="scan target")
        config = LLMConfig(provider="openai", api_key="test", model="test-model")
        agent = CustomAgent(
            session_id=123,
            session_title="scan target",
            payload=payload,
            config=config,
        )

        async def save_user_message():
            calls.append("save_user")
            return 10

        async def create_assistant_placeholder():
            calls.append("create_assistant")
            return 20

        async def update_assistant_periodically(*args):
            calls.append("start_periodic_update")
            await args[2].wait()

        async def load_history(*, user_msg_id, assistant_msg_id):
            calls.append(("load_history", user_msg_id, assistant_msg_id))
            return [HumanMessage(content="previous")]

        async def execute(**kwargs):
            calls.append("execute")
            return [
                *kwargs["history_messages"],
                HumanMessage(content="scan target"),
                AIMessage(
                    content="done",
                    usage_metadata={
                        "input_tokens": 3,
                        "output_tokens": 2,
                        "total_tokens": 5,
                    },
                ),
            ]

        async def save_final_messages(**kwargs):
            calls.append(("save_final", kwargs["assistant_msg_id"]))
            calls.append(("run_metadata", kwargs["run_metadata"]))
            calls.append(
                (
                    "saved_agents",
                    [
                        getattr(message, "name", None)
                        for message in kwargs["new_messages"]
                    ],
                )
            )
            return "done"

        calls = []
        monkeypatch.setattr(agent._messages, "save_user_message", save_user_message)
        monkeypatch.setattr(
            agent._messages,
            "create_assistant_placeholder",
            create_assistant_placeholder,
        )
        monkeypatch.setattr(
            agent._messages,
            "update_assistant_periodically",
            update_assistant_periodically,
        )
        monkeypatch.setattr(agent._messages, "load_history", load_history)
        monkeypatch.setattr(agent._runtime, "execute", execute)
        monkeypatch.setattr(agent._messages, "save_final_messages", save_final_messages)

        queue: asyncio.Queue[AgentStreamEvent | None] = asyncio.Queue()
        callback = StreamCallbackHandler(queue, asyncio.get_running_loop())
        await agent._run_agent(queue, callback, None)

        events = await _collect_until_closed(queue)
        assert ("done", {"text": "done", "session_id": 123}) in events
        assert [event for event in events if event[0] == "error"] == []

        core_calls = [call for call in calls if call != "start_periodic_update"]
        assert core_calls == [
            "save_user",
            "create_assistant",
            ("load_history", 10, 20),
            "execute",
            ("save_final", 20),
            ("run_metadata", {"tool_events": [], "mcp_events": []}),
            ("saved_agents", ["main_agent"]),
        ]
        assert "start_periodic_update" in calls

    asyncio.run(run_agent())


def test_session_agent_registry_reuses_agent_reference():
    session_endpoint._drop_session_agent(123)
    config = LLMConfig(provider="openai", api_key="test", model="test-model")
    active_session = AgentSession(id=123, title="session")

    first = session_endpoint._get_session_agent(
        active_session=active_session,
        payload=AgentRunRequest(config_id=1, input="first"),
        config=config,
        agent_configs={},
    )
    second = session_endpoint._get_session_agent(
        active_session=active_session,
        payload=AgentRunRequest(config_id=1, input="second"),
        config=config,
        agent_configs={},
    )

    assert first is second
    assert second.input_text == "second"
    assert second._runtime is first._runtime
    session_endpoint._drop_session_agent(123)
