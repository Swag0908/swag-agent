"""Markdown 笔记导入边界：本地绝对路径 / 浏览器上传 / 附件发现与链接改写。

1:1 复刻 Java `NotesImportService`：

- 本地路径导入只允许 ``settings.notes_import_roots`` 白名单内的绝对路径，且仅 ``.md``；
- 上传用 ``relativePaths`` 保留目录层级，附件从同批上传项里按相对路径解析；
- 引用附件复制到 ``<home>/.resources/<bundle-uuid>/``，链接改写为
  ``/api/notes/resource?bundle=<uuid>&name=<encoded>``；
- 限制：单篇 Markdown ``notes_max_markdown_bytes``（2 MiB）、单附件
  ``notes_max_attachment_bytes``（20 MiB）、单批总量 ``notes_max_import_total_bytes``（100 MiB）。
"""

from __future__ import annotations

import mimetypes
import os
import posixpath
import re
import shutil
import urllib.parse
import uuid
from dataclasses import dataclass
from pathlib import Path

from app.config import settings
from app.core.errors import AppError, BadRequest, Forbidden, NotFound
from app.domains.notes import views
from app.domains.notes.service import (
    RESOURCES_DIR,
    UNCLASSIFIED,
    NotesService,
    delete_tree,
)

#: Markdown 行内链接/图片；路径里有空格时应使用 <...> 或 URL 编码。
_INLINE_LINK = re.compile(r"(!?\[[^\r\n]*?]\(\s*)(<[^>\r\n]+>|[^\s)]+)([^\r\n)]*\))")

#: Markdown 引用式链接定义：[id]: path "title"。
_REFERENCE_LINK = re.compile(r"(?m)^(\s{0,3}\[[^\r\n]+]:\s*)(<[^>\r\n]+>|\S+)(.*)$")

#: Markdown 中的原生 HTML 资源属性（脚本内容不会执行，前端仍会过 DOMPurify）。
_HTML_LINK = re.compile(r"(\b(?:src|href)\s*=\s*[\"'])([^\"']+)([\"'])", re.IGNORECASE)

#: Obsidian 常见的附件语法。
_WIKI_EMBED = re.compile(r"(!\[\[)([^|\]\r\n]+)([^\]\r\n]*]])")

#: bundle 编号形状（与 Java 正则一致）。
_BUNDLE_ID_RE = re.compile(r"[0-9a-fA-F-]{36}")

#: 浏览器内联展示的图片类型；其余强制 attachment 下载。
_INLINE_EXTENSIONS = (".png", ".jpg", ".jpeg", ".gif", ".webp", ".avif")

#: Java URLEncoder 视为不编码的字符（a-zA-Z0-9 与 . - * _）。
_URL_SAFE = "*-._"


@dataclass
class UploadPart:
    """一个上传项：浏览器给的相对路径 + 文件名 + 已读入的字节内容。"""

    relative_path: str | None
    original_filename: str | None
    content: bytes


@dataclass(frozen=True)
class LinkTarget:
    """本地链接去掉 URL 查询/锚点后的路径与后缀。"""

    decoded_path: str
    suffix: str

    @classmethod
    def parse(cls, raw: str | None) -> LinkTarget | None:
        if raw is None or not raw.strip():
            return None
        value = raw.strip()
        lower = value.lower()
        if (
            value.startswith("#")
            or value.startswith("//")
            or lower.startswith(
                ("http:", "https:", "data:", "mailto:", "tel:", "javascript:")
            )
        ):
            return None
        suffix_at = len(value)
        query = value.find("?")
        fragment = value.find("#")
        if query >= 0:
            suffix_at = min(suffix_at, query)
        if fragment >= 0:
            suffix_at = min(suffix_at, fragment)
        path = value[:suffix_at]
        if not path.strip():
            return None
        suffix = value[suffix_at:]
        try:
            if path.lower().startswith("file:"):
                parsed = urllib.parse.urlparse(path)
                return cls(urllib.parse.unquote(parsed.path), suffix)
            return cls(urllib.parse.unquote(path.replace("+", "%2B")), suffix)
        except (ValueError, UnicodeDecodeError):
            return cls(path, suffix)


def _file_name(path: str | None) -> str:
    idx = -1 if path is None else path.rfind("/")
    return path if idx < 0 else path[idx + 1 :]


def _parent_of(path: str) -> str:
    idx = path.rfind("/")
    return "" if idx < 0 else path[:idx]


def _is_markdown(path: str | None) -> bool:
    return path is not None and path.lower().endswith(".md")


def _safe_resource_name(path: str) -> str:
    name = re.sub(r"[\x00-\x1F\x7F/\\]", "_", _file_name(path))
    return name if name.strip() else "attachment"


def _url_encode(value: str) -> str:
    """与 Java URLEncoder.encode(UTF_8).replace("+", "%20") 对齐。"""
    return urllib.parse.quote(value, safe=_URL_SAFE).replace("~", "%7E")


def _reason(exc: BaseException) -> str:
    if isinstance(exc, AppError):
        return exc.message
    message = str(exc)
    return message if message.strip() else type(exc).__name__


def _delete_quietly(path: Path | None) -> None:
    if path is None:
        return
    try:
        delete_tree(path)
    except OSError:
        pass


def _normalize_relative(value: str) -> str:
    slash = value.replace("\\", "/").strip()
    if slash.startswith("/") or re.match(r"^[A-Za-z]:/", slash):
        raise BadRequest(f"上传相对路径非法：{value}")
    result = posixpath.normpath(slash) if slash else "."
    if not result or result in (".", "..") or result.startswith("../"):
        raise BadRequest(f"上传相对路径非法：{value}")
    return result


def _normalize_upload_path(supplied: str | None, fallback: str | None) -> str:
    value = supplied if supplied is not None and supplied.strip() else fallback
    if value is None or not value.strip():
        raise BadRequest("上传文件缺少文件名")
    return _normalize_relative(value)


def _replace_targets(text: str, pattern: re.Pattern[str], importer: object) -> str:
    """按 Java replaceTargets 语义替换捕获组 2；importer 返回 None 时保留原样。"""
    out: list[str] = []
    last = 0
    for match in pattern.finditer(text):
        raw = match.group(2)
        angled = raw.startswith("<") and raw.endswith(">")
        plain = raw[1:-1] if angled else raw
        replacement = importer(plain)  # type: ignore[operator]
        if replacement is None:
            continue
        final_target = f"<{replacement}>" if angled else replacement
        out.append(text[last : match.start(2)])
        out.append(final_target)
        last = match.end(2)
    out.append(text[last:])
    return "".join(out)


class _BatchBudget:
    """一次批量导入（Markdown + 附件）的总读取预算。"""

    def __init__(self, max_bytes: int) -> None:
        self._max = max_bytes
        self._used = 0

    def add(self, size: int) -> None:
        if size < 0 or self._used > self._max - size:
            raise AppError(413, f"本次批量导入超过总量上限（{self._max} 字节）")
        self._used += size


class _BatchResult:
    def __init__(self) -> None:
        self.imported: list[str] = []
        self.failed: list[views.ImportFailure] = []
        self.warnings: list[str] = []
        self.attachments_copied = 0

    def view(self) -> views.ImportResult:
        return views.ImportResult(
            list(self.imported),
            list(self.failed),
            list(self.warnings),
            self.attachments_copied,
        )


class _ResourceBundle:
    """一次 Markdown 导入对应的附件目录（``.resources/<uuid>``）。"""

    def __init__(self, home: Path, budget: _BatchBudget, warnings: list[str]) -> None:
        self.id = str(uuid.uuid4())
        self.directory = home / RESOURCES_DIR / self.id
        self.directory = Path(os.path.normpath(self.directory))
        self._budget = budget
        self._warnings = warnings
        self._copied: dict[str, str] = {}
        self.copied_count = 0
        self.directory.mkdir(parents=True, exist_ok=True)

    # ---- 复制 ----

    def copy_local(self, source: Path) -> str:
        key = str(source)
        existing = self._copied.get(key)
        if existing is not None:
            return existing
        size = source.stat().st_size
        self._require_attachment_size(size, str(source))
        self._budget.add(size)
        target = self._unique_resource(_safe_resource_name(source.name))
        shutil.copy2(source, target)
        return self._remember(key, target.name)

    def copy_upload(self, relative_path: str, part: UploadPart) -> str:
        existing = self._copied.get(relative_path)
        if existing is not None:
            return existing
        size = len(part.content)
        self._require_attachment_size(size, relative_path)
        self._budget.add(size)
        target = self._unique_resource(_safe_resource_name(relative_path))
        target.write_bytes(part.content)
        return self._remember(relative_path, target.name)

    # ---- 内部 ----

    def _require_attachment_size(self, size: int, source: str) -> None:
        if size > settings.notes_max_attachment_bytes:
            raise AppError(413, f"附件超过导入上限：{source}")

    def _unique_resource(self, name: str) -> Path:
        candidate = self.directory / name
        dot = name.rfind(".")
        stem = name[:dot] if dot > 0 else name
        ext = name[dot:] if dot > 0 else ""
        index = 1
        while os.path.lexists(candidate):
            candidate = self.directory / f"{stem} ({index}){ext}"
            index += 1
        return candidate

    def _remember(self, key: str, name: str) -> str:
        url = f"/api/notes/resource?bundle={self.id}&name={_url_encode(name)}"
        self._copied[key] = url
        self.copied_count += 1
        return url

    def warn(self, warning: str) -> None:
        self._warnings.append(warning)

    def remove_if_empty(self) -> None:
        if self.copied_count == 0:
            _delete_quietly(self.directory)


class NotesImportService:
    """笔记导入服务；磁盘读写委托给 ``NotesService``。"""

    def __init__(self, notes_service: NotesService | None = None) -> None:
        from app.domains.notes.service import get_notes_service

        self._notes = notes_service if notes_service is not None else get_notes_service()

    # ---------- 配置 ----------

    def config(self) -> views.ImportConfig:
        return views.ImportConfig(_configured_import_roots())

    # ---------- 本地路径导入 ----------

    def import_local(
        self,
        user_id: int | None,
        source_paths: list[str] | None,
        target_dir: str | None,
    ) -> views.ImportResult:
        requested = [
            path.strip()
            for path in (source_paths or [])
            if path is not None and path.strip()
        ]
        if not requested:
            raise BadRequest("请至少提供一个 .md 文件路径")

        batch = _BatchResult()
        budget = _BatchBudget(settings.notes_max_import_total_bytes)
        roots = self._import_roots()
        for source_text in requested:
            bundle: Path | None = None
            try:
                source = self._allowed_local_file(Path(source_text), roots, markdown=True)
                size = source.stat().st_size
                self._require_markdown_size(size, source_text)
                budget.add(size)
                markdown = source.read_bytes().decode("utf-8", errors="replace")

                resources = _ResourceBundle(self._notes.home_dir(user_id), budget, batch.warnings)
                bundle = resources.directory
                rewritten = self._rewrite_links(
                    markdown,
                    lambda target: self._import_local_attachment(
                        source, target, roots, resources, source_text
                    ),
                )
                saved = self._notes.create_unique(
                    user_id, self._normalized_target_dir(target_dir), source.name, rewritten
                )
                resources.remove_if_empty()
                batch.imported.append(saved.path)
                batch.attachments_copied += resources.copied_count
            except Exception as exc:  # noqa: BLE001 - 批量导入不因单个来源失败而中断
                _delete_quietly(bundle)
                batch.failed.append(views.ImportFailure(source_text, _reason(exc)))
        return batch.view()

    # ---------- 浏览器上传导入 ----------

    def import_uploads(
        self,
        user_id: int | None,
        parts: list[UploadPart] | None,
        target_dir: str | None,
    ) -> views.ImportResult:
        if not parts:
            raise BadRequest("请选择要导入的文件")
        files: dict[str, UploadPart] = {}
        for part in parts:
            if part is None or part.content is None:
                continue
            relative = _normalize_upload_path(part.relative_path, part.original_filename)
            if relative in files:
                raise BadRequest(f"上传内容包含重复路径：{relative}")
            files[relative] = part
        markdown_paths = [path for path in files if _is_markdown(path)]
        if not markdown_paths:
            raise BadRequest("所选内容中没有 .md 文件")

        batch = _BatchResult()
        budget = _BatchBudget(settings.notes_max_import_total_bytes)
        for markdown_path in markdown_paths:
            bundle: Path | None = None
            try:
                uploaded = files[markdown_path]
                size = len(uploaded.content)
                self._require_markdown_size(size, markdown_path)
                budget.add(size)
                markdown = uploaded.content.decode("utf-8", errors="replace")

                resources = _ResourceBundle(self._notes.home_dir(user_id), budget, batch.warnings)
                bundle = resources.directory
                rewritten = self._rewrite_links(
                    markdown,
                    lambda target: self._import_uploaded_attachment(
                        markdown_path, target, files, resources
                    ),
                )
                saved = self._notes.create_unique(
                    user_id,
                    self._normalized_target_dir(target_dir),
                    _file_name(markdown_path),
                    rewritten,
                )
                resources.remove_if_empty()
                batch.imported.append(saved.path)
                batch.attachments_copied += resources.copied_count
            except Exception as exc:  # noqa: BLE001 - 批量导入不因单个来源失败而中断
                _delete_quietly(bundle)
                batch.failed.append(views.ImportFailure(markdown_path, _reason(exc)))
        return batch.view()

    # ---------- 附件读取 ----------

    def resource(self, user_id: int | None, bundle_id: str | None, name: str | None) -> views.ResourceView:
        if bundle_id is None or not _BUNDLE_ID_RE.fullmatch(bundle_id):
            raise BadRequest("资源编号非法")
        if (
            name is None
            or not name.strip()
            or "/" in name
            or "\\" in name
            or name in (".", "..")
        ):
            raise BadRequest("资源名称非法")
        root = Path(os.path.normpath(self._notes.home_dir(user_id) / RESOURCES_DIR / bundle_id))
        file = Path(os.path.normpath(root / name))
        if not file.is_relative_to(root) or not os.path.isfile(file) or os.path.islink(file):
            raise NotFound("导入资源不存在")
        try:
            real_root = Path(os.path.realpath(root))
            real_file = Path(os.path.realpath(file))
            if not real_file.is_relative_to(real_root):
                raise Forbidden("资源路径越界")
            content_type = mimetypes.guess_type(real_file.name)[0]
            if not content_type:
                content_type = "application/octet-stream"
            inline = name.lower().endswith(_INLINE_EXTENSIONS)
            return views.ResourceView(real_file, name, content_type, inline)
        except OSError as exc:
            raise AppError(500, "读取导入资源失败") from exc

    # ---------- 内部：链接改写 ----------

    def _rewrite_links(self, markdown: str, importer: object) -> str:
        rewritten = _replace_targets(markdown, _INLINE_LINK, importer)
        rewritten = _replace_targets(rewritten, _REFERENCE_LINK, importer)
        rewritten = _replace_targets(rewritten, _HTML_LINK, importer)
        return _replace_targets(rewritten, _WIKI_EMBED, importer)

    def _import_local_attachment(
        self,
        markdown: Path,
        raw_target: str,
        roots: list[Path],
        resources: _ResourceBundle,
        source_label: str,
    ) -> str | None:
        target = LinkTarget.parse(raw_target)
        if target is None:
            return None
        try:
            requested = Path(target.decoded_path)
            candidate = requested if requested.is_absolute() else markdown.parent / requested
            attachment = self._allowed_local_file(candidate, roots, markdown=False)
            url = resources.copy_local(attachment)
            return url + target.suffix
        except Exception as exc:  # noqa: BLE001 - 附件失败只警告并保留原链接
            resources.warn(f"「{source_label}」未复制附件 {raw_target}：{_reason(exc)}")
            return None

    def _import_uploaded_attachment(
        self,
        markdown_path: str,
        raw_target: str,
        files: dict[str, UploadPart],
        resources: _ResourceBundle,
    ) -> str | None:
        target = LinkTarget.parse(raw_target)
        if target is None:
            return None
        try:
            decoded = Path(target.decoded_path)
            if target.decoded_path.startswith("/") or decoded.is_absolute():
                resources.warn(
                    f"「{markdown_path}」中的绝对附件路径无法通过浏览器上传解析：{raw_target}"
                )
                return None
            base = _parent_of(markdown_path)
            candidate = _normalize_relative(
                f"{base}/{target.decoded_path}" if base else target.decoded_path
            )
            attachment = files.get(candidate)
            if attachment is None:
                resources.warn(
                    f"「{markdown_path}」缺少所引用的上传附件：{raw_target}"
                    "（选择包含附件的文件夹即可一并导入）"
                )
                return None
            url = resources.copy_upload(candidate, attachment)
            return url + target.suffix
        except Exception as exc:  # noqa: BLE001 - 附件失败只警告并保留原链接
            resources.warn(f"「{markdown_path}」未复制附件 {raw_target}：{_reason(exc)}")
            return None

    # ---------- 内部：路径与限制 ----------

    def _import_roots(self) -> list[Path]:
        roots: list[Path] = []
        for raw in _configured_import_roots():
            try:
                root = Path(raw).expanduser().resolve(strict=True)
            except OSError:
                continue
            if root.is_dir():
                roots.append(root)
        if not roots:
            raise Forbidden("本地路径导入未配置可读取目录（app.notes.import-roots）")
        return roots

    def _allowed_local_file(self, requested: Path, roots: list[Path], *, markdown: bool) -> Path:
        if not requested.is_absolute():
            raise BadRequest(f"本地导入必须使用绝对路径：{requested}")
        real = requested.resolve(strict=True)
        if not any(real.is_relative_to(root) for root in roots):
            raise Forbidden(f"路径不在允许导入的目录内：{requested}")
        if not real.is_file():
            raise BadRequest(f"不是普通文件：{requested}")
        if markdown and not _is_markdown(real.name):
            raise BadRequest(f"仅支持导入 .md 文件：{requested}")
        return real

    def _require_markdown_size(self, size: int, source: str) -> None:
        if size > settings.notes_max_markdown_bytes:
            raise AppError(413, f"Markdown 文件超过导入上限：{source}")

    @staticmethod
    def _normalized_target_dir(target_dir: str | None) -> str:
        return UNCLASSIFIED if target_dir is None or not target_dir.strip() else target_dir.strip()


def _configured_import_roots() -> list[str]:
    return [raw.strip() for raw in settings.notes_import_roots.split(",") if raw.strip()]


_default_import_service: NotesImportService | None = None


def get_import_service() -> NotesImportService:
    """进程内默认导入服务（依赖默认 NotesService）。"""
    global _default_import_service
    if _default_import_service is None:
        _default_import_service = NotesImportService()
    return _default_import_service
