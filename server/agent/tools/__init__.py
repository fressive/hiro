"""Tool package auto-registration."""

from __future__ import annotations

import importlib
import pkgutil
from pathlib import Path

from langchain_core.tools import BaseTool


_PACKAGE_DIR = Path(__file__).resolve().parent


def _load_tool_modules() -> list[object]:
	modules: list[object] = []
	for module_info in pkgutil.iter_modules([str(_PACKAGE_DIR)]):
		if module_info.name.startswith("_"):
			continue
		modules.append(importlib.import_module(f"{__name__}.{module_info.name}"))
	return modules


def _collect_tools(modules: list[object]) -> list[BaseTool]:
	tools: list[BaseTool] = []
	for module in modules:
		for value in vars(module).values():
			if isinstance(value, BaseTool):
				tools.append(value)
	return tools


_modules = _load_tool_modules()
agent_tools = _collect_tools(_modules)

__all__ = ["agent_tools"]