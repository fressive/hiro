import asyncio
from contextlib import AsyncExitStack

from langchain_core.messages import AIMessage, HumanMessage

from server.agent.custom_agent import CustomAgent
from server.agent.events.streaming import AgentStreamEvent, StreamCallbackHandler
from server.agent.runtime.run_context import AgentRunContext
from server.models.llm import LLMConfig
from server.schemas.agent import AgentRunRequest


def _parse_stream_event(raw_event: AgentStreamEvent):
    return raw_event.event, raw_event.data


async def _collect_until_done(queue: asyncio.Queue[AgentStreamEvent | None]):
    events = []
    while True:
        raw_event = await queue.get()
        assert raw_event is not None
        event = _parse_stream_event(raw_event)
        events.append(event)
        if event[0] == "done":
            return events


def test_custom_agent_execution_graph_persists_done_event(monkeypatch):
    async def run_graph():
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

        async def load_mcp_tools(server_names, exit_stack):
            calls.append("load_mcp")
            return []

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
        monkeypatch.setattr("server.agent.custom_agent.load_mcp_tools", load_mcp_tools)
        monkeypatch.setattr(agent._messages, "load_history", load_history)
        monkeypatch.setattr(agent._runtime, "execute", execute)
        monkeypatch.setattr(agent._messages, "save_final_messages", save_final_messages)

        queue: asyncio.Queue[AgentStreamEvent | None] = asyncio.Queue()
        callback = StreamCallbackHandler(queue, asyncio.get_running_loop())
        async with AsyncExitStack() as exit_stack:
            context = AgentRunContext(
                queue=queue,
                callback=callback,
                agent_done=asyncio.Event(),
                exit_stack=exit_stack,
            )
            await agent._execution_graph.ainvoke({"run": context})

        events = await _collect_until_done(queue)
        done_event = events[-1]
        assert done_event == (
            "done",
            {
                "text": "done",
                "session_id": 123,
            },
        )
        graph_events = [event for event in events if event[0] == "graph_node"]
        assert graph_events[0] == (
            "graph_node",
            {"id": "persist_input", "status": "running"},
        )
        assert graph_events[-1] == (
            "graph_node",
            {"id": "persist_output", "status": "done"},
        )
        assert ("graph_node", {"id": "writeup", "status": "skipped"}) in graph_events
        assert done_event[1] == {
            "text": "done",
            "session_id": 123,
        }
        core_calls = [call for call in calls if call != "start_periodic_update"]
        assert core_calls == [
            "save_user",
            "create_assistant",
            "load_mcp",
            ("load_history", 10, 20),
            "execute",
            ("save_final", 20),
        ]
        assert "start_periodic_update" in calls

    asyncio.run(run_graph())


def test_custom_agent_execution_graph_routes_to_writeup_node(monkeypatch):
    async def run_graph():
        payload = AgentRunRequest(config_id=1, input="请根据前面步骤生成报告")
        config = LLMConfig(provider="openai", api_key="test", model="test-model")
        agent = CustomAgent(
            session_id=123,
            session_title="report",
            payload=payload,
            config=config,
        )

        async def save_user_message():
            return 10

        async def create_assistant_placeholder():
            return 20

        async def update_assistant_periodically(*args):
            await args[2].wait()

        async def load_mcp_tools(server_names, exit_stack):
            return []

        async def load_history(*, user_msg_id, assistant_msg_id):
            return [HumanMessage(content="found /admin")]

        async def execute(**kwargs):
            return [
                *kwargs["history_messages"],
                HumanMessage(content="请根据前面步骤生成报告"),
                AIMessage(content="Verified exposed admin panel."),
            ]

        async def generate_writeup(run):
            calls.append("writeup")
            return AIMessage(content="# Report\n\nFound exposed admin panel.")

        async def save_writeup_artifact(report_markdown):
            calls.append(("artifact", report_markdown))

        async def save_final_messages(**kwargs):
            calls.append(
                [
                    getattr(message, "content", "")
                    for message in kwargs["new_messages"]
                ]
            )
            return "Verified exposed admin panel."

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
        monkeypatch.setattr("server.agent.custom_agent.load_mcp_tools", load_mcp_tools)
        monkeypatch.setattr(agent._messages, "load_history", load_history)
        monkeypatch.setattr(agent._runtime, "execute", execute)
        monkeypatch.setattr(agent, "_generate_writeup", generate_writeup)
        monkeypatch.setattr(agent, "_save_writeup_artifact", save_writeup_artifact)
        monkeypatch.setattr(agent._messages, "save_final_messages", save_final_messages)

        queue: asyncio.Queue[AgentStreamEvent | None] = asyncio.Queue()
        callback = StreamCallbackHandler(queue, asyncio.get_running_loop())
        async with AsyncExitStack() as exit_stack:
            context = AgentRunContext(
                queue=queue,
                callback=callback,
                agent_done=asyncio.Event(),
                exit_stack=exit_stack,
            )
            await agent._execution_graph.ainvoke({"run": context})

        events = await _collect_until_done(queue)
        done_event = events[-1]
        graph_events = [event for event in events if event[0] == "graph_node"]
        assert done_event == (
            "done",
            {
                "text": "# Report\n\nFound exposed admin panel.",
                "session_id": 123,
            },
        )
        assert ("graph_node", {"id": "writeup", "status": "running"}) in graph_events
        assert ("graph_node", {"id": "writeup", "status": "done"}) in graph_events
        assert done_event[1] == {
            "text": "# Report\n\nFound exposed admin panel.",
            "session_id": 123,
        }
        assert "writeup" in calls
        assert ("artifact", "# Report\n\nFound exposed admin panel.") in calls
        assert [
            "Verified exposed admin panel.",
            "# Report\n\nFound exposed admin panel.",
        ] in calls

    asyncio.run(run_graph())
