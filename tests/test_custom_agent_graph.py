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


async def _collect_until_closed(queue: asyncio.Queue[AgentStreamEvent | None]):
    events = []
    while True:
        raw_event = await queue.get()
        if raw_event is None:
            return events
        events.append(_parse_stream_event(raw_event))


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
        monkeypatch.setattr(
            "server.agent.graph.execution_graph.load_mcp_tools",
            load_mcp_tools,
        )
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
        assert (
            "graph_node",
            {"id": "information_collect", "status": "skipped"},
        ) in graph_events
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


def test_custom_agent_execution_graph_routes_to_information_collect_node(monkeypatch):
    async def run_graph():
        payload = AgentRunRequest(
            config_id=1,
            input="collect information for https://target.test",
        )
        config = LLMConfig(provider="openai", api_key="test", model="default-model")
        agent = CustomAgent(
            session_id=123,
            session_title="collect information",
            payload=payload,
            config=config,
            agent_configs={
                "information_collect_agent": LLMConfig(
                    provider="openai",
                    api_key="test",
                    model="collect-model",
                ),
                "main_agent": LLMConfig(
                    provider="openai",
                    api_key="test",
                    model="main-model",
                ),
            },
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
            return [HumanMessage(content="previous hint")]

        async def generate_information_collect(run):
            calls.append("information_collect")
            return AIMessage(content="## Scope\n- https://target.test")

        async def append_information_collect_artifact(collection_markdown):
            calls.append(("info_artifact", collection_markdown))

        async def execute(**kwargs):
            calls.append(("execute_prompt", kwargs["full_system_prompt"]))
            return [
                *kwargs["history_messages"],
                HumanMessage(content=payload.input),
                AIMessage(content="main done"),
            ]

        async def save_final_messages(**kwargs):
            calls.append(
                (
                    "saved_agents",
                    [
                        getattr(message, "name", None)
                        for message in kwargs["new_messages"]
                    ],
                )
            )
            calls.append(("agent_models", kwargs["agent_models"]))
            return "main done"

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
        monkeypatch.setattr(
            "server.agent.graph.execution_graph.load_mcp_tools",
            load_mcp_tools,
        )
        monkeypatch.setattr(agent._messages, "load_history", load_history)
        monkeypatch.setattr(
            agent._execution_graph,
            "_generate_information_collect",
            generate_information_collect,
        )
        monkeypatch.setattr(
            agent._execution_graph,
            "_append_information_collect_artifact",
            append_information_collect_artifact,
        )
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
        graph_events = [event for event in events if event[0] == "graph_node"]
        assert (
            "graph_node",
            {"id": "information_collect", "status": "running"},
        ) in graph_events
        assert (
            "graph_node",
            {"id": "information_collect", "status": "done"},
        ) in graph_events
        assert (
            "info_artifact",
            "## Scope\n- https://target.test",
        ) in calls
        assert (
            "saved_agents",
            ["information_collect_agent", "main_agent"],
        ) in calls
        assert (
            "agent_models",
            {
                "information_collect_agent": "collect-model",
                "main_agent": "main-model",
                "writeup_agent": "default-model",
            },
        ) in calls
        prompt_calls = [
            call[1]
            for call in calls
            if isinstance(call, tuple) and call[0] == "execute_prompt"
        ]
        assert prompt_calls
        assert "INFORMATION COLLECTION BRIEF" in prompt_calls[0]
        assert "https://target.test" in prompt_calls[0]
        assert calls.index("information_collect") < calls.index(
            ("execute_prompt", prompt_calls[0])
        )
        assert events[-1] == (
            "done",
            {
                "text": "main done",
                "session_id": 123,
            },
        )

    asyncio.run(run_graph())


def test_custom_agent_ignores_mcp_cleanup_error_after_done(monkeypatch):
    async def run_graph():
        payload = AgentRunRequest(
            config_id=1,
            input="scan target",
            mcp_servers=["broken-cleanup"],
        )
        config = LLMConfig(provider="openai", api_key="test", model="test-model")
        agent = CustomAgent(
            session_id=123,
            session_title="scan target",
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
            async def cleanup():
                raise RuntimeError("Session termination failed: 501")

            exit_stack.push_async_callback(cleanup)
            return []

        async def load_history(*, user_msg_id, assistant_msg_id):
            return []

        async def execute(**kwargs):
            return [
                HumanMessage(content="scan target"),
                AIMessage(content="done"),
            ]

        async def save_final_messages(**kwargs):
            return "done"

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
        await agent._run_agent(queue, callback, None)

        events = await _collect_until_closed(queue)
        assert ("done", {"text": "done", "session_id": 123}) in events
        assert [event for event in events if event[0] == "error"] == []

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
            calls.append(
                (
                    "saved_agents",
                    [
                        getattr(message, "name", None)
                        for message in kwargs["new_messages"]
                    ],
                )
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
        monkeypatch.setattr(
            "server.agent.graph.execution_graph.load_mcp_tools",
            load_mcp_tools,
        )
        monkeypatch.setattr(agent._messages, "load_history", load_history)
        monkeypatch.setattr(agent._runtime, "execute", execute)
        monkeypatch.setattr(
            agent._execution_graph,
            "_generate_writeup",
            generate_writeup,
        )
        monkeypatch.setattr(
            agent._execution_graph,
            "_save_writeup_artifact",
            save_writeup_artifact,
        )
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
        assert ("saved_agents", ["main_agent", "writeup_agent"]) in calls

    asyncio.run(run_graph())
