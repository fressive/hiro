"""Shared DeepAgent subagent declaration primitives."""

from collections.abc import Callable
from pathlib import Path
from typing import Any, ClassVar

from deepagents.backends import CompositeBackend, FilesystemBackend, StateBackend

from server.agent.utils.tool_call_ids import ToolCallIdMiddleware

LOCAL_SKILLS_ROOT = Path("./skills")


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
    def skills(
        cls,
        build_skill_sources: Callable[[str], list[str]],
    ) -> list[str]:
        """Return DeepAgent skill source routes for this subagent."""

        if cls.skill_source_dir is None:
            return []
        return build_skill_sources(cls.skill_source_dir)

    @classmethod
    def local_skill_sources(
        cls,
        skill_sources: list[str] | None,
    ) -> list[str]:
        """Return local skill source folders for direct subagent invocations."""

        if skill_sources is not None:
            return [Path(source).as_posix() for source in skill_sources]
        if cls.skill_source_dir is None:
            return []
        source = LOCAL_SKILLS_ROOT / cls.skill_source_dir
        if not source.is_dir():
            return []
        return [source.as_posix()]

    @classmethod
    def local_skills_backend(cls, skill_sources: list[str]) -> CompositeBackend:
        """Return a backend that exposes local skill folders without host FS writes."""

        return CompositeBackend(
            default=StateBackend(),
            routes={
                f"{source.rstrip('/')}/": FilesystemBackend(
                    source,
                    virtual_mode=True,
                    max_file_size_mb=10,
                )
                for source in skill_sources
            },
        )

    @classmethod
    def to_deepagent_config(
        cls,
        *,
        build_llm: Callable[[str], Any],
        build_skill_sources: Callable[[str], list[str]],
    ) -> dict[str, Any]:
        """Return the dict schema consumed by DeepAgent."""

        return {
            "name": cls.name,
            "description": cls.description,
            "system_prompt": cls.system_prompt,
            "model": build_llm(cls.name),
            "tools": cls.tools(),
            "skills": cls.skills(build_skill_sources),
            "middleware": cls.middleware(),
        }
