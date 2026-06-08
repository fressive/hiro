"""LLM construction and execution for session-scoped agents."""

import asyncio
from typing import Any

from deepagents import create_deep_agent
from deepagents.backends import CompositeBackend, FilesystemBackend
from deepagents.middleware.subagents import GENERAL_PURPOSE_SUBAGENT
from langchain.chat_models import init_chat_model
from langchain_core.messages import BaseMessage, HumanMessage

from server.agent.events.streaming import StreamCallbackHandler
from server.agent.runtime.context import SessionContext
from server.agent.runtime.sandboxed_backend import SessionSandboxedBackend
from server.agent.tools import agent_tools
from server.agent.utils.tool_call_ids import ToolCallIdMiddleware
from server.core.logger import logger
from server.core.util import get_data_path
from server.models.llm import LLMConfig
from server.schemas.agent import AgentRunRequest

SYSTEM_PROMPT = """"""
INFORMATION_COLLECT_AGENT_NAME = "information_collect_agent"
WRITEUP_AGENT_NAME = "writeup_agent"
MAX_STREAMING_ATTEMPTS = 2
STREAM_RETRY_BACKOFF_SECONDS = 0.5
RETRYABLE_STREAM_ERROR_MARKERS = (
    "empty_stream",
    "error code: 408",
    "stream error",
    "stream disconnected before completion",
    "stream closed before response.completed",
    "upstream stream closed before first payload",
    "response.completed",
    "remoteprotocolerror",
    "incompleteread",
)

SPECIALIZED_SUBAGENT_DESCRIPTIONS = [
    {
        "name": INFORMATION_COLLECT_AGENT_NAME,
        "description": (
            "Use proactively for target information collection, reconnaissance "
            "briefs, scope extraction, URL/host discovery, and collection plans "
            "before deeper penetration-testing work."
        ),
    },
    {
        "name": WRITEUP_AGENT_NAME,
        "description": (
            "Use for writeups, reports, summaries, and final Markdown reporting "
            "from prior conversation, tool output, evidence, and artifacts."
        ),
    },
]
SUBAGENT_DELEGATION_PROMPT = """## Workflow Subagent Delegation

The main agent is one node in a larger execution graph. The graph owns
specialized workflow subagents and invokes them through graph routing, not
through the main agent's `task` tool.

Workflow-managed specialized subagents:
{subagent_descriptions}

Delegation rules:
- For writeups, reports, summaries, or final Markdown reporting, do not draft
  the report directly in the main agent. Preserve the relevant evidence and let
  the workflow route to `writeup_agent`.
- For target information collection, reconnaissance briefs, scope extraction,
  URL/host discovery, or collection planning, do not perform that collection
  directly in the main agent. Preserve the request context and let the workflow
  route to `information_collect_agent`.
- Do not call the `task` tool with `writeup_agent` or
  `information_collect_agent`; those are graph nodes, not inner DeepAgent task
  subagents.
- Use the main agent only to coordinate, verify, gather evidence, and present
  results that are not owned by a specialized workflow subagent."""


def is_retryable_stream_error(error: BaseException) -> bool:
    """Return whether an exception represents a transient stream disconnect."""

    if isinstance(error, BaseExceptionGroup):
        return any(is_retryable_stream_error(child) for child in error.exceptions)

    status_code = getattr(error, "status_code", None)
    if status_code == 408:
        return True

    message = str(error).lower()
    return any(marker in message for marker in RETRYABLE_STREAM_ERROR_MARKERS)


class AgentRuntime:
    """Build models, prompts, tools, and execution backends for one run.

    This class deliberately does not own persistence, streaming queue lifetime,
    or LangGraph routing. It is the execution adapter used by graph nodes when
    they need an LLM, selected tools, the effective system prompt, or a
    session-scoped filesystem backend.
    """

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
        """Combine session prompt, MCP usage guidance, and RAG context."""

        full_system_prompt = self.payload.system_prompt or SYSTEM_PROMPT
        if mcp_tools:
            # MCP tools are exposed through router tools, so the model needs
            # explicit instructions instead of seeing every remote tool eagerly.
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

    def build_main_agent_prompt(self, full_system_prompt: str) -> str:
        """Append project-specific subagent delegation rules for DeepAgent."""

        descriptions = "\n".join(
            f"- `{item['name']}`: {item['description']}"
            for item in SPECIALIZED_SUBAGENT_DESCRIPTIONS
        )
        section = SUBAGENT_DELEGATION_PROMPT.format(
            subagent_descriptions=descriptions,
        )
        if not full_system_prompt.strip():
            return section
        return f"{full_system_prompt}\n\n{section}"

    async def execute(
        self,
        *,
        history_messages: list[BaseMessage],
        mcp_tools: list[Any],
        full_system_prompt: str,
        callback: StreamCallbackHandler,
    ) -> list[Any]:
        """Run the main agent and return the complete message sequence."""

        current_tools = self.selected_builtin_tools() + mcp_tools
        skills_sources = ["./skills"]
        main_system_prompt = self.build_main_agent_prompt(full_system_prompt)

        for attempt in range(1, MAX_STREAMING_ATTEMPTS + 2):
            streaming = attempt <= MAX_STREAMING_ATTEMPTS
            checkpoint_id = f"execute-agent-{attempt}"
            snapshot = callback.snapshot() if callback is not None else None
            if callback is not None:
                callback.emit_event("live_checkpoint", {"id": checkpoint_id})

            try:
                messages = await self._execute_deep_agent(
                    current_tools=current_tools,
                    skills_sources=skills_sources,
                    main_system_prompt=main_system_prompt,
                    callback=callback,
                    history_messages=history_messages,
                    streaming=streaming,
                )
                if callback is not None:
                    callback.emit_event("live_commit", {"id": checkpoint_id})
                return messages
            except Exception as exc:
                if not streaming or not is_retryable_stream_error(exc):
                    if callback is not None:
                        callback.emit_event("live_commit", {"id": checkpoint_id})
                    raise

                if callback is not None and snapshot is not None:
                    callback.rollback(snapshot)
                    callback.emit_event(
                        "live_rollback",
                        {
                            "id": checkpoint_id,
                            "attempt": attempt,
                            "retrying": True,
                            "fallback": attempt == MAX_STREAMING_ATTEMPTS,
                            "message": "Stream disconnected; retrying the model call.",
                        },
                    )
                logger.warning(
                    "Retryable stream error in session %s on attempt %s: %s",
                    self.session_id,
                    attempt,
                    exc,
                )
                await asyncio.sleep(STREAM_RETRY_BACKOFF_SECONDS * attempt)

        raise RuntimeError("Agent execution retry loop exited unexpectedly")

    async def _execute_deep_agent(
        self,
        *,
        current_tools: list[Any],
        skills_sources: list[str],
        main_system_prompt: str,
        callback: StreamCallbackHandler,
        history_messages: list[BaseMessage],
        streaming: bool,
    ) -> list[Any]:
        """Execute one DeepAgent attempt."""

        llm = self.build_llm("main_agent", streaming=streaming)
        agent = create_deep_agent(
            llm,
            tools=current_tools,
            context_schema=SessionContext,
            backend=self.build_backend(),
            skills=skills_sources,
            system_prompt=main_system_prompt,
            middleware=[ToolCallIdMiddleware()],
            subagents=self.build_subagents(skills_sources),
        )
        result_state = await agent.ainvoke(
            {"messages": history_messages + [HumanMessage(content=self.input_text)]},
            config={"callbacks": [callback]} if callback is not None else None,
            context=SessionContext(self.session_id),
        )
        return result_state.get("messages", [])

    def build_subagents(self, skills_sources: list[str]) -> list[dict[str, Any]]:
        """Return inner DeepAgent task subagents exposed to the main agent."""

        return [
            {
                **GENERAL_PURPOSE_SUBAGENT,
                "skills": skills_sources,
                "middleware": [ToolCallIdMiddleware()],
            },
        ]

    def build_llm(
        self,
        agent_name: str | None = None,
        *,
        streaming: bool = True,
    ) -> Any:
        """Create a LangChain chat model for the requested graph agent."""

        config = self.agent_config(agent_name)
        provider = config.provider.lower()
        model_name = config.model.lower()
        # Claude-compatible configs may arrive with a generic provider name;
        # LangChain needs the Anthropic provider to select the right client.
        if model_name.startswith("claude") or "anthropic" in model_name:
            provider = "anthropic"

        base_url = config.base_url
        # Anthropic clients expect the base host, while many proxy configs are
        # stored with an OpenAI-compatible /v1 suffix.
        if provider == "anthropic" and base_url and base_url.endswith("/v1"):
            base_url = base_url.rsplit("/v1", 1)[0]

        model_kwargs: dict[str, Any] = {}
        if config.enable_1m_context:
            # 1M-context support is provider-specific and must be passed through
            # the provider's native opt-in parameter.
            if provider == "openai":
                model_kwargs["enable_1m_context"] = True
            elif provider == "anthropic":
                model_kwargs["betas"] = ["context-1m-2025-08-07"]

        init_kwargs: dict[str, Any] = {
            "model": config.model,
            "model_provider": provider,
            "api_key": config.api_key,
            "base_url": base_url,
            "streaming": streaming,
            "max_retries": 5,
        }
        if not streaming:
            init_kwargs["disable_streaming"] = True
        elif provider == "openai" and base_url:
            init_kwargs["stream_usage"] = False

        if self.payload.temperature is not None:
            init_kwargs["temperature"] = self.payload.temperature
        if self.payload.max_tokens is not None:
            init_kwargs["max_tokens"] = self.payload.max_tokens

        return init_chat_model(**init_kwargs, **model_kwargs)

    def agent_config(self, agent_name: str | None) -> LLMConfig:
        """Return the per-agent model config, falling back to session default."""

        if agent_name and agent_name in self.agent_configs:
            return self.agent_configs[agent_name]
        return self.config

    def agent_model_name(self, agent_name: str) -> str:
        """Return the resolved model name used for persisted message metadata."""

        return self.agent_config(agent_name).model

    def selected_builtin_tools(self) -> list[Any]:
        """Return built-in tools enabled by the run payload."""

        if self.payload.tools is None:
            return []
        return [tool for tool in agent_tools if tool.name in self.payload.tools]

    def build_backend(self) -> CompositeBackend:
        """Create the DeepAgent backend for session-local file operations."""

        data_path = get_data_path(self.session_id)
        
        # Use route to expose the actual path of files on the host to LLM to ensure 
        # that components not in the bwrap sandbox (MCP Server i.e.) can retrieve the 
        # file correctly.
        return CompositeBackend(
            default=SessionSandboxedBackend(self.session_id),
            routes={
                f"{str(data_path.absolute())}/": FilesystemBackend(
                    data_path,
                    virtual_mode=True,
                    max_file_size_mb=1000,
                )
            },
        )
