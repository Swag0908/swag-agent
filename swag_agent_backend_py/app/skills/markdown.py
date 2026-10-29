"""SKILL.md 解析器：YAML frontmatter（name/description）+ Markdown 正文。

逐行移植 Java `SkillMarkdown.java` 的校验规则，保证同一目录在 Java/Python 两侧
加载结果一致：
- 文件必须以 `---` 开头，且 frontmatter 有结束 `---`；
- 必须有非空 description；
- name 必须是 kebab-case（`[a-z0-9]+(?:-[a-z0-9]+)*`），缺省时回退目录名；
- 解析失败返回 error 由调用方跳过并告警，不阻断启动。
"""

from __future__ import annotations

import re
from dataclasses import dataclass

_VALID_NAME = re.compile(r"[a-z0-9]+(?:-[a-z0-9]+)*")


@dataclass(frozen=True)
class ParsedSkill:
    name: str
    description: str
    body: str


@dataclass(frozen=True)
class ParseResult:
    parsed: ParsedSkill | None
    error: str | None = None

    @property
    def ok(self) -> bool:
        return self.parsed is not None


def _invalid(reason: str) -> ParseResult:
    return ParseResult(parsed=None, error=reason)


def _ok(parsed: ParsedSkill) -> ParseResult:
    return ParseResult(parsed=parsed, error=None)


def _parse_fields(frontmatter: str) -> dict[str, str]:
    """极简 frontmatter 解析：只认单行 `key: value`，忽略注释与空行，保留首个同名字段。"""
    fields: dict[str, str] = {}
    for line in frontmatter.split("\n"):
        trimmed = line.strip()
        if not trimmed or trimmed.startswith("#"):
            continue
        colon = trimmed.find(":")
        if colon <= 0:
            continue
        key = trimmed[:colon].strip().lower()
        value = trimmed[colon + 1 :].strip()
        quoted = len(value) >= 2 and (
            (value.startswith('"') and value.endswith('"'))
            or (value.startswith("'") and value.endswith("'"))
        )
        if quoted:
            value = value[1:-1].strip()
        fields.setdefault(key, value)
    return fields


def parse(folder_name: str | None, raw: str | None) -> ParseResult:
    """解析一份 SKILL.md；folder_name 用于 frontmatter 未写 name 时兜底。"""
    if raw is None or not raw.strip():
        return _invalid("文件为空")

    text = raw.replace("\r\n", "\n").replace("\r", "\n").lstrip()
    if text.startswith("\ufeff"):
        text = text[1:].lstrip()
    if not text.startswith("---"):
        return _invalid("缺少 YAML frontmatter（文件应以 --- 开头）")

    first_line_end = text.find("\n")
    if first_line_end < 0:
        return _invalid("frontmatter 未闭合")

    fence_start = -1
    fence_line_end = -1
    cursor = first_line_end + 1
    while cursor <= len(text):
        line_end = text.find("\n", cursor)
        line = text[cursor:] if line_end < 0 else text[cursor:line_end]
        if line.strip() == "---":
            fence_start = cursor
            fence_line_end = len(text) if line_end < 0 else line_end
            break
        if line_end < 0:
            break
        cursor = line_end + 1

    if fence_start < 0:
        return _invalid("frontmatter 未闭合（缺少结束的 ---）")

    fields = _parse_fields(text[first_line_end + 1 : fence_start])
    body = text[fence_line_end:].strip()

    description = fields.get("description", "").strip()
    if not description:
        return _invalid("frontmatter 缺少 description")

    name = fields.get("name", "").strip()
    if not name:
        name = (folder_name or "").strip()
    if not _VALID_NAME.fullmatch(name):
        return _invalid(f"技能名不是 kebab-case：{name}")
    return _ok(ParsedSkill(name=name, description=description, body=body))
