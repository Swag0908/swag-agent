"""工具包入口：按契约顺序 import 各来源模块，触发 `@tool` 注册。

CONTRACTS §1：顺序为 `datetime_tool`、`web_search`、`app.domains.todo.tools`、
`app.domains.sites.tools`、`app.domains.notes.tools`、`app.memory.tools`；
**不存在的模块跳过**（各模块并行开发，谁先落地谁先可用）。
"""

from __future__ import annotations

import importlib
import logging

logger = logging.getLogger(__name__)

_TOOL_MODULES = (
    "app.agent.tools.datetime_tool",
    "app.agent.tools.web_search",
    "app.domains.todo.tools",
    "app.domains.sites.tools",
    "app.domains.notes.tools",
    "app.memory.tools",
)

_loaded = False
_LOADED_MODULES: list[str] = []


def load_all(force: bool = False) -> list[str]:
    """加载所有可用工具模块，返回实际导入成功的模块名。幂等。"""
    global _loaded
    if _loaded and not force:
        return list(_LOADED_MODULES)
    loaded: list[str] = []
    for module_name in _TOOL_MODULES:
        try:
            importlib.import_module(module_name)
        except ModuleNotFoundError as exc:
            if exc.name == module_name:
                logger.debug("tool module %s 尚未实现，跳过", module_name)
                continue
            raise
        loaded.append(module_name)
    _LOADED_MODULES[:] = loaded
    _loaded = True
    return loaded


def loaded_modules() -> list[str]:
    return list(_LOADED_MODULES)


__all__ = ["load_all", "loaded_modules"]
