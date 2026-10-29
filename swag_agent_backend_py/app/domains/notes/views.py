"""Markdown 笔记 REST 视图对象（与 Java NotesViews.java 字段逐字对齐）。

字段名即 JSON 名（camelCase），FastAPI 的 jsonable_encoder 可直接序列化 dataclass。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class Node:
    """目录树节点：dir 带 children（file 的 children 为空数组）。"""

    name: str
    path: str
    type: str  # "dir" | "file"
    children: list[Node] = field(default_factory=list)


@dataclass
class FileView:
    """一篇笔记的完整内容；modified 为 epoch 毫秒。"""

    path: str
    name: str
    size: int
    modified: int
    content: str


@dataclass
class SaveResult:
    """保存成功后的回执；modified 为 epoch 毫秒。"""

    path: str
    size: int
    modified: int


@dataclass
class ImportFailure:
    """单个导入来源的失败信息。"""

    source: str
    reason: str


@dataclass
class ImportResult:
    """批量导入结果；imported 是实际落盘路径（重名时自动加序号）。"""

    imported: list[str]
    failed: list[ImportFailure]
    warnings: list[str]
    attachmentsCopied: int


@dataclass
class ImportConfig:
    """前端展示用的导入边界。"""

    localRoots: list[str]


@dataclass
class TrashView:
    """回收站条目；kind: file | dir，deletedAt 为 epoch 毫秒。"""

    id: str
    originalPath: str
    name: str
    kind: str
    deletedAt: int


@dataclass
class ResourceView:
    """导入附件读取结果（API 层据此构造响应）。"""

    path: Path
    fileName: str
    contentType: str
    inline: bool
