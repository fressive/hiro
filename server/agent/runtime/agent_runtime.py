"""LLM construction and execution for session-scoped agents."""

from typing import Any

from deepagents import create_deep_agent
from deepagents.backends import CompositeBackend, FilesystemBackend, StateBackend
from deepagents.middleware.subagents import GENERAL_PURPOSE_SUBAGENT
from langchain.chat_models import init_chat_model
from langchain_core.messages import BaseMessage, HumanMessage, SystemMessage

from server.agent.events.streaming import StreamCallbackHandler
from server.agent.runtime.context import SessionContext
from server.agent.utils.tool_call_ids import ToolCallIdMiddleware, normalize_model_messages
from server.agent.tools import agent_tools
from server.core.util import get_data_path
from server.models.llm import LLMConfig
from server.schemas.agent import AgentRunRequest


class AgentRuntime:
    def __init__(
        self,
        *,
        session_id: int,
        input_text: str,
        payload: AgentRunRequest,
        config: LLMConfig,
        agent_configs: dict[str, LLMConfig] | None = None,
    ) -> None:
        self.session_id = session_id
        self.input_text = input_text
        self.payload = payload
        self.config = config
        self.agent_configs = agent_configs or {}

    def build_system_prompt(self, *, mcp_tools: list[Any], rag_context: str) -> str:
        full_system_prompt = self.payload.system_prompt or ""
        if mcp_tools:
            full_system_prompt += (
                "\n\nMCP access is lazy-loaded through two router tools: "
                "use mcp_search to find available MCP tools and schemas, then "
                "use mcp_call with the exact tool_name and JSON arguments."
            )
        if rag_context:
            full_system_prompt += (
                "\n\nRELEVANT CONTEXT FROM DOCUMENTS:\n"
                f"{rag_context}"
            )
        return full_system_prompt

    async def execute(
        self,
        *,
        history_messages: list[BaseMessage],
        mcp_tools: list[Any],
        full_system_prompt: str,
        callback: StreamCallbackHandler,
    ) -> list[Any]:
        llm = self.build_llm("main_agent")
        current_tools = self.selected_builtin_tools() + mcp_tools

        if self.payload.is_deep_agent:
            skills_sources = ["./skills"]
            agent = create_deep_agent(
                llm,
                tools=current_tools,
                context_schema=SessionContext,
                backend=self.build_backend(),
                skills=skills_sources,
                system_prompt=full_system_prompt,
                middleware=[ToolCallIdMiddleware()],
                subagents=[
                    {
                        **GENERAL_PURPOSE_SUBAGENT,
                        "skills": skills_sources,
                        "middleware": [ToolCallIdMiddleware()],
                    }
                ],
            )
            result_state = await agent.ainvoke(
                {
                    "messages": history_messages
                    + [HumanMessage(content=self.input_text)]
                },
                config={"callbacks": [callback]},
                context=SessionContext(self.session_id),
            )
            return result_state.get("messages", [])

        llm_messages: list[BaseMessage] = []
        if full_system_prompt:
            llm_messages.append(SystemMessage(content=full_system_prompt))
        llm_messages.extend(history_messages)
        llm_messages.append(HumanMessage(content=self.input_text))
        llm_with_tools = llm.bind_tools(current_tools) if current_tools else llm
        result_payload = await llm_with_tools.ainvoke(
            llm_messages,
            config={"callbacks": [callback]},
        )
        result_messages = (
            result_payload if isinstance(result_payload, list) else [result_payload]
        )
        return (
            history_messages
            + [HumanMessage(content=self.input_text)]
            + normalize_model_messages(result_messages)
        )

    def build_llm(self, agent_name: str | None = None) -> Any:
        config = self.agent_config(agent_name)
        provider = config.provider.lower()
        model_name = config.model.lower()
        if model_name.startswith("claude") or "anthropic" in model_name:
            provider = "anthropic"

        base_url = config.base_url
        if provider == "anthropic" and base_url and base_url.endswith("/v1"):
            base_url = base_url.rsplit("/v1", 1)[0]

        model_kwargs: dict[str, Any] = {}
        if config.enable_1m_context:
            if provider == "openai":
                model_kwargs["enable_1m_context"] = True
            elif provider == "anthropic":
                model_kwargs["betas"] = ["context-1m-2025-08-07"]

        init_kwargs: dict[str, Any] = {
            "model": config.model,
            "model_provider": provider,
            "api_key": config.api_key,
            "base_url": base_url,
            "streaming": True,
            "max_retries": 5,
        }

        if self.payload.temperature is not None:
            init_kwargs["temperature"] = self.payload.temperature
        if self.payload.max_tokens is not None:
            init_kwargs["max_tokens"] = self.payload.max_tokens

        return init_chat_model(**init_kwargs, **model_kwargs)

    def agent_config(self, agent_name: str | None) -> LLMConfig:
        if agent_name and agent_name in self.agent_configs:
            return self.agent_configs[agent_name]
        return self.config

    def agent_model_name(self, agent_name: str) -> str:
        return self.agent_config(agent_name).model

    def selected_builtin_tools(self) -> list[Any]:
        if self.payload.tools is None:
            return []
        return [tool for tool in agent_tools if tool.name in self.payload.tools]

    def build_backend(self) -> CompositeBackend:
        data_path = get_data_path(self.session_id)
        return CompositeBackend(
            default=StateBackend(),
            routes={
                f"{str(data_path.absolute())}/": FilesystemBackend(
                    data_path,
                    virtual_mode=True,
                    max_file_size_mb=1000,
                )
            },
        )
