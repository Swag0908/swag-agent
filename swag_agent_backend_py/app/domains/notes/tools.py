"""笔记领域 Agent 工具：``importLocalMarkdownNotes``。

对应 Java `NotesTools`（`J/notes/NotesTools.java`）。用户身份只从 ``ToolCtx.user_id`` 取，
业务失败返回中文文案而不是抛异常，便于模型转述给用户。
"""

from __future__ import annotations

from starlette.concurrency import run_in_threadpool

from app.core.errors import AppError
from app.domains.notes import views
from app.domains.notes.import_service import get_import_service

try:  # chat-core 的注册表可能尚未落地；缺失时退化为普通函数，不阻塞其它模块
    from app.agent.tools.registry import ToolCtx, tool
except ModuleNotFoundError:  # pragma: no cover - 注册表就绪后走上面的分支
    ToolCtx = object  # type: ignore[assignment,misc]

    def tool(*_args, **_kwargs):  # type: ignore[no-redef]
        def decorator(func):
            return func

        return decorator


TOOL_NAME = "importLocalMarkdownNotes"

TOOL_DESCRIPTION = (
    "把运行本项目的机器上的一个或多个本地 .md 文件导入当前用户的 Markdown 笔记。"
    "sourcePaths 必须是用户给出的绝对路径，且位于服务端配置允许的导入目录中；"
    "会复制 Markdown 引用的本地图片、脚本和附件并改写链接。"
    "targetFolder 是笔记库中已存在的目标文件夹，用户未指定时传「未分类」。"
    "同名笔记不会覆盖，会自动加 (1)、(2) 后缀。"
)

TOOL_PARAMETERS = {
    "type": "object",
    "properties": {
        "sourcePaths": {
            "type": "array",
            "items": {"type": "string"},
            "description": "要导入的本地 .md 绝对路径列表",
        },
        "targetFolder": {
            "type": "string",
            "description": "笔记库内的目标文件夹路径；未指定时传「未分类」",
        },
    },
    "required": ["sourcePaths", "targetFolder"],
    "additionalProperties": False,
}


def _format_result(result: views.ImportResult) -> str:
    """与 Java NotesTools 的返回文案逐字对齐。"""
    message = ""
    if result.imported:
        message += (
            f"已导入 {len(result.imported)} 篇笔记："
            + "、".join(result.imported)
            + f"；复制附件 {result.attachmentsCopied} 个。"
        )
    if result.failed:
        if message:
            message += "\n"
        message += f"导入失败 {len(result.failed)} 个："
        for failure in result.failed:
            message += f"\n- {failure.source}：{failure.reason}"
    if result.warnings:
        if message:
            message += "\n"
        message += "附件提示："
        for warning in result.warnings:
            message += f"\n- {warning}"
    return message if message else "没有可导入的 Markdown 文件。"


@tool(
    TOOL_NAME,
    TOOL_DESCRIPTION,
    TOOL_PARAMETERS,
    needs_user=True,
    side_effect="write",
)
async def import_local_markdown_notes(
    sourcePaths: list[str],
    targetFolder: str,
    ctx: ToolCtx,
) -> str:
    user_id = getattr(ctx, "user_id", None)
    if user_id is None:
        return "未登录，无法导入 Markdown 笔记。"
    try:
        result = await run_in_threadpool(
            get_import_service().import_local, user_id, sourcePaths, targetFolder
        )
    except AppError as exc:
        return exc.message
    except Exception as exc:  # noqa: BLE001 - 工具层不抛异常，交回模型转述
        return f"导入 Markdown 笔记失败：{exc}"
    return _format_result(result)
