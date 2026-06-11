"""Shared DeepAgent subagent declaration primitives."""

from collections.abc import Callable
from pathlib import Path
from typing import Any, ClassVar

from server.agent.utils.tool_call_ids import ToolCallIdMiddleware


class SubAgent:
    """Base class for agents exposed through DeepAgent's task tool."""

    name: ClassVar[str]
    description: ClassVar[str]
    system_prompt: ClassVar[str]
    skill_source_dir: ClassVar[str | None] = None
    delegation_rule: ClassVar[str | None] = None
    order: ClassVar[int] = 100

    @classmethod
    def tools(cls) -> list[Any]:
        """Return tools available to this subagent."""

        return []

    @classmethod
    def middleware(cls) -> list[Any]:
        """Return middleware applied to this subagent."""

        return [ToolCallIdMiddleware()]

    @classmethod
    def to_deepagent_config(
        cls,
        *,
        build_llm: Callable[[str], Any],
        extra_tools: list[Any] | None = None,
    ) -> dict[str, Any]:
        """Return the dict schema consumed by DeepAgent."""

        return {
            "name": cls.name,
            "description": cls.description,
            "system_prompt": cls.system_prompt,
            "model": build_llm(cls.name),
            "tools": [*cls.tools(), *(extra_tools or [])],
            "skills": [
                (Path("./skills") / cls.skill_source_dir).resolve().as_posix()
            ]
            if cls.skill_source_dir
            and (Path("./skills") / cls.skill_source_dir).is_dir()
            else [],
            "middleware": cls.middleware(),
        }
