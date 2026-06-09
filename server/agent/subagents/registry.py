"""Automatic discovery for DeepAgent subagent classes."""

import importlib
import pkgutil
from functools import lru_cache

from server.agent.subagents.base import SubAgent

_PACKAGE_NAME = "server.agent.subagents"
_DISCOVERY_SKIP_MODULES = {
    f"{_PACKAGE_NAME}.base",
    f"{_PACKAGE_NAME}.registry",
}


@lru_cache
def load_subagent_classes() -> tuple[type[SubAgent], ...]:
    """Import subagent modules and return declared DeepAgent subagent classes."""

    package = importlib.import_module(_PACKAGE_NAME)
    for module_info in pkgutil.iter_modules(package.__path__, f"{_PACKAGE_NAME}."):
        if module_info.name in _DISCOVERY_SKIP_MODULES:
            continue
        importlib.import_module(module_info.name)

    classes = {
        subagent_class
        for subagent_class in _all_subclasses(SubAgent)
        if getattr(subagent_class, "name", None)
        and subagent_class.__module__.startswith(f"{_PACKAGE_NAME}.")
    }
    return tuple(
        sorted(
            classes,
            key=lambda subagent_class: (
                subagent_class.order,
                subagent_class.name,
            ),
        )
    )
def _all_subclasses(
    base_class: type[SubAgent],
) -> set[type[SubAgent]]:
    subclasses: set[type[SubAgent]] = set()
    for subclass in base_class.__subclasses__():
        subclasses.add(subclass)
        subclasses.update(_all_subclasses(subclass))
    return subclasses
