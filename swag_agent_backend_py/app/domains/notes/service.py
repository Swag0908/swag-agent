"""Markdown 笔记的磁盘读写服务（1:1 复刻 Java `NotesService` 语义）。

笔记存放在 ``<settings.notes_root>/user-<userId>``，对外全部使用相对路径（``/`` 分隔）。
目录模型：

- ``未分类``：每用户默认文件夹，放散笔记（根目录新建 / 恢复兜底 / 删文件夹平铺）；
- ``.trash``：隐藏回收站，删除的笔记/文件夹先进这里，7 天后清理，可恢复
  （原目录仍在则放回原处，否则进「未分类」）；
- ``.resources``：导入时复制的引用附件（读取入口在 ``import_service``）。

安全：拒绝对路径、``..``、空段、控制字符、以点开头的保留段（含 ``.trash``/
``.resources``），并对已存在前缀做 realpath 校验，防止经符号链接逃逸出用户目录。
"""

from __future__ import annotations

import os
import re
import shutil
import uuid
from pathlib import Path

from app.config import settings
from app.core.errors import AppError, BadRequest, Forbidden, NotFound
from app.core.timeutil import epoch_ms, now
from app.domains.notes import views

#: 默认「未分类」文件夹名。
UNCLASSIFIED = "未分类"

#: 每用户隐藏回收站目录名（点开头，不进目录树）。
TRASH_DIR = ".trash"

#: 导入附件目录名。
RESOURCES_DIR = ".resources"

#: 回收站元数据文件名（内容实际是 3 行 key=value properties 文本，不是 JSON）。
ENTRY_META = "entry.json"

#: 回收站默认保留天数（可用 settings.notes_trash_retention_days 覆盖）。
DEFAULT_RETENTION_DAYS = 7

#: 回收站条目编号格式（Java 同款：8-64 位字母/数字/连字符）。
_TRASH_ID_RE = re.compile(r"^[0-9A-Za-z-]{8,64}$")


def now_ms() -> int:
    """当前 epoch 毫秒（与 Java System.currentTimeMillis 对齐）。"""
    return epoch_ms(now())


def _retention_ms() -> int:
    try:
        days = int(settings.notes_trash_retention_days)
    except (TypeError, ValueError):  # pragma: no cover - 配置异常兜底
        days = DEFAULT_RETENTION_DAYS
    return max(days, 0) * 24 * 3600 * 1000


def _max_note_bytes() -> int:
    try:
        return int(settings.notes_max_markdown_bytes)
    except (TypeError, ValueError):  # pragma: no cover - 配置异常兜底
        return 2 * 1024 * 1024


def _io_error(message: str) -> AppError:
    return AppError(500, message)


def _conflict(message: str) -> AppError:
    return AppError(409, message)


def display_rel(path: Path, home: Path) -> str:
    """把 home 内的路径转成对外相对路径（``/`` 分隔）；home 本身返回空串。"""
    try:
        rel = path.relative_to(home)
    except ValueError:  # pragma: no cover - 调用方保证 path 在 home 内
        return path.name
    return "" if rel == Path(".") else rel.as_posix()


def file_name(rel: str | None) -> str:
    idx = -1 if rel is None else rel.rfind("/")
    return rel if idx < 0 else rel[idx + 1 :]


def require_note_extension(rel: str | None) -> None:
    if not (rel or "").lower().endswith(".md"):
        raise BadRequest(f"仅支持 .md 笔记文件：{rel}")


def validate_segment(seg: str, rel: str | None) -> None:
    for char in seg:
        code = ord(char)
        if code < 0x20 or code == 0x7F:
            raise BadRequest(f"路径包含非法字符：{rel}")
    if seg.endswith("."):
        raise BadRequest(f"路径不能以点结尾：{rel}")


def is_safe_relative(rel: str | None) -> bool:
    """判断一个相对路径是否满足 guard 的静态规则（用于校验回收站元数据）。"""
    if rel is None:
        return False
    cleaned = rel.replace("\\", "/").strip()
    if not cleaned or cleaned.startswith("/"):
        return False
    try:
        for seg in cleaned.split("/"):
            if not seg or seg == "." or seg == ".." or seg.startswith("."):
                return False
            validate_segment(seg, rel)
    except BadRequest:
        return False
    return True


def _assert_no_symlink_escape(home: Path, target: Path) -> None:
    """对已存在前缀做 realpath 校验，防止符号链接把读写带出用户目录。"""
    real_home = Path(os.path.realpath(home))
    probe = target
    missing: list[str] = []
    while not os.path.lexists(probe):
        parent = probe.parent
        if parent == probe:  # 到达文件系统根
            break
        missing.append(probe.name)
        probe = parent
    real = Path(os.path.realpath(probe))
    if not real.is_relative_to(real_home):
        raise Forbidden(f"路径超出笔记目录：{target.name}")
    verified = real
    for seg in reversed(missing):
        verified = verified / seg
    if not verified.is_relative_to(real_home):
        raise Forbidden("路径超出笔记目录")


def guard(home: Path, rel: str | None) -> Path:
    """把相对路径解析到用户目录内并做防逃逸校验（对应 Java NotesService.guard）。"""
    cleaned = "" if rel is None else rel.replace("\\", "/").strip()
    if cleaned.startswith("/"):
        raise BadRequest(f"不接受绝对路径：{rel}")
    if not cleaned:
        raise BadRequest("路径不能为空")
    resolved = home
    for seg in cleaned.split("/"):
        if not seg or seg == "." or seg == ".." or seg.startswith("."):
            raise BadRequest(f"非法路径：{rel}")
        validate_segment(seg, rel)
        resolved = resolved / seg
    resolved = Path(os.path.normpath(resolved))
    if not resolved.is_relative_to(home):
        raise Forbidden(f"路径越界：{rel}")
    try:
        _assert_no_symlink_escape(home, resolved)
    except OSError as exc:  # pragma: no cover - realpath 极少失败
        raise _io_error("校验笔记路径失败") from exc
    return resolved


def delete_tree(path: Path) -> None:
    """递归删除；不跟随符号链接（对应 Java deleteTree）。"""
    if not os.path.lexists(path):
        return
    if path.is_dir() and not path.is_symlink():
        shutil.rmtree(path)
    else:
        path.unlink()


def move_within(source: Path, target: Path) -> None:
    """同卷原子移动；跨卷（EXDEV / ATOMIC_MOVE 不支持）回退普通移动。"""
    target.parent.mkdir(parents=True, exist_ok=True)
    try:
        os.replace(source, target)
    except OSError as exc:
        if getattr(exc, "errno", None) not in (None, 18, 45):  # 18=EXDEV, 45=EOPNOTSUPP
            raise
        shutil.move(str(source), str(target))


def unique_target(directory: Path, name: str) -> Path:
    """在目录内取可用名字；重名则加 `` (n)``。"""
    directory.mkdir(parents=True, exist_ok=True)
    candidate = directory / name
    if not os.path.lexists(candidate):
        return candidate
    dot = name.rfind(".")
    stem = name[:dot] if dot > 0 else name
    ext = name[dot:] if dot > 0 else ""
    index = 1
    while True:
        candidate = directory / f"{stem} ({index}){ext}"
        if not os.path.lexists(candidate):
            return candidate
        index += 1


def unique_resource_name(directory: Path, name: str) -> Path:
    """导入附件去重命名（与 Java ResourceBundle.uniqueResource 一致）。"""
    candidate = directory / name
    dot = name.rfind(".")
    stem = name[:dot] if dot > 0 else name
    ext = name[dot:] if dot > 0 else ""
    index = 1
    while os.path.lexists(candidate):
        candidate = directory / f"{stem} ({index}){ext}"
        index += 1
    return candidate


# ---------------------------------------------------------------------------
# 回收站元数据：entry.json 实际是 3 行 key=value 文本，绝不能按 JSON 解析
# ---------------------------------------------------------------------------


def write_entry_meta(entry_dir: Path, original_rel: str, kind: str) -> None:
    content = f"originalPath={original_rel}\nkind={kind}\ndeletedAt={now_ms()}\n"
    (entry_dir / ENTRY_META).write_text(content, encoding="utf-8")


def read_entry_meta(entry_dir: Path) -> tuple[str, str, int] | None:
    """解析 entry.json；形状非法 / originalPath 不安全时返回 None（坏条目）。"""
    meta_file = entry_dir / ENTRY_META
    try:
        if not meta_file.is_file():
            return None
        original_path: str | None = None
        kind: str | None = None
        deleted_at = 0
        for line in meta_file.read_text(encoding="utf-8").splitlines():
            idx = line.find("=")
            if idx <= 0:
                continue
            key = line[:idx]
            value = line[idx + 1 :]
            if key == "originalPath":
                original_path = value
            elif key == "kind":
                kind = value
            elif key == "deletedAt":
                try:
                    deleted_at = int(value.strip())
                except ValueError:
                    pass
        if original_path is None or not original_path.strip() or deleted_at <= 0:
            return None
        if kind not in ("file", "dir"):
            return None
        # 加固：原路径必须是我们写过的合法相对路径，避免被篡改的元数据把恢复写出 home
        if not is_safe_relative(original_path):
            return None
        return original_path, kind, deleted_at
    except (OSError, UnicodeDecodeError):
        return None


def entry_data_path(entry_dir: Path, kind: str) -> Path:
    return entry_dir / ("note.md" if kind == "file" else "content")


class NotesService:
    """笔记磁盘读写服务。

    ``root`` 为空时使用 ``settings.notes_root_path``（测试可注入临时目录）。
    """

    def __init__(self, root: str | Path | None = None) -> None:
        self._root = Path(root).expanduser().resolve() if root is not None else None

    @property
    def root(self) -> Path:
        return self._root if self._root is not None else settings.notes_root_path

    # ---------- 目录 ----------

    def home_dir(self, user_id: int | None) -> Path:
        if user_id is None:
            raise AppError(401, "未登录")
        return self.root / f"user-{user_id}"

    def ensure_home(self, user_id: int | None) -> Path:
        home = self.home_dir(user_id)
        try:
            home.mkdir(parents=True, exist_ok=True)
            (home / UNCLASSIFIED).mkdir(parents=True, exist_ok=True)
        except OSError as exc:
            raise _io_error("无法初始化笔记目录") from exc
        return home

    def ensure_unclassified(self, home: Path) -> Path:
        path = home / UNCLASSIFIED
        path.mkdir(parents=True, exist_ok=True)
        return path

    # ---------- 常规操作 ----------

    def tree(self, user_id: int) -> views.Node:
        try:
            return self._build_node(self.ensure_home(user_id), f"user-{user_id}", "")
        except OSError as exc:
            raise _io_error("读取笔记目录失败") from exc

    def _build_node(self, directory: Path, name: str, rel: str) -> views.Node:
        children: list[views.Node] = []
        entries = [
            entry
            for entry in directory.iterdir()
            if not entry.name.startswith(".") and not entry.is_symlink()
        ]
        entries.sort(key=lambda entry: (not entry.is_dir(), entry.name.lower()))
        for entry in entries:
            entry_name = entry.name
            entry_rel = entry_name if not rel else f"{rel}/{entry_name}"
            if entry.is_dir():
                children.append(self._build_node(entry, entry_name, entry_rel))
            elif entry_name.lower().endswith(".md"):
                children.append(views.Node(entry_name, entry_rel, "file", []))
        return views.Node(name, rel, "dir", children)

    def read(self, user_id: int, rel: str) -> views.FileView:
        require_note_extension(rel)
        home = self.ensure_home(user_id)
        file = guard(home, rel)
        if not file.exists():
            raise NotFound(f"笔记不存在：{rel}")
        if file.is_dir():
            raise BadRequest(f"「{rel}」是文件夹，不是笔记文件")
        try:
            stat = file.stat()
            content = file.read_bytes().decode("utf-8")
        except UnicodeDecodeError as exc:
            raise _io_error(f"读取笔记失败：{rel}") from exc
        except OSError as exc:
            raise _io_error(f"读取笔记失败：{rel}") from exc
        return views.FileView(rel, file_name(rel), stat.st_size, int(stat.st_mtime * 1000), content)

    def create(self, user_id: int, rel: str, content: str | None) -> views.SaveResult:
        return self._write(user_id, rel, content, overwrite=False)

    def save(self, user_id: int, rel: str, content: str | None) -> views.SaveResult:
        return self._write(user_id, rel, content, overwrite=True)

    def _write(self, user_id: int, rel: str, content: str | None, *, overwrite: bool) -> views.SaveResult:
        require_note_extension(rel)
        data = (content or "").encode("utf-8")
        max_bytes = _max_note_bytes()
        if len(data) > max_bytes:
            raise AppError(413, f"笔记超过大小上限（{max_bytes // 1024 // 1024} MiB）")
        home = self.ensure_home(user_id)
        file = guard(home, rel)
        if file.is_dir():
            raise BadRequest(f"「{rel}」已存在且是文件夹")
        if not overwrite and os.path.lexists(file):
            raise _conflict(f"已存在同名笔记：{rel}")
        try:
            parent = file.parent
            if not parent.is_dir():
                raise NotFound(f"父目录不存在：{display_rel(parent, home)}")
            if overwrite:
                with open(file, "wb") as handle:
                    handle.write(data)
            else:
                # O_EXCL：创建与判重在同一个原子操作里，并发下也不会覆盖已有笔记
                fd = os.open(file, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o666)
                try:
                    os.write(fd, data)
                finally:
                    os.close(fd)
            stat = file.stat()
            return views.SaveResult(rel, stat.st_size, int(stat.st_mtime * 1000))
        except FileExistsError as exc:
            raise _conflict(f"已存在同名笔记：{rel}") from exc
        except AppError:
            raise
        except OSError as exc:
            raise _io_error(f"保存笔记失败：{rel}") from exc

    def create_unique(
        self, user_id: int, target_dir: str | None, source_file_name: str, content: str
    ) -> views.SaveResult:
        """在目标文件夹内以来源文件名创建笔记；同名自动加序号，绝不覆盖。"""
        raw = "" if source_file_name is None else str(source_file_name).replace("\\", "/")
        name = file_name(raw)
        if not name.strip() or name != (source_file_name if source_file_name is not None else ""):
            raise BadRequest(f"导入文件名非法：{source_file_name}")
        require_note_extension(name)

        home = self.ensure_home(user_id)
        parent = "" if target_dir is None else target_dir.strip()
        if parent:
            self._require_dir(home, parent)
        dot = name.rfind(".")
        stem = name[:dot] if dot > 0 else name
        ext = name[dot:] if dot > 0 else ""
        index = 0
        while True:
            candidate_name = name if index == 0 else f"{stem} ({index}){ext}"
            rel = candidate_name if not parent else f"{parent}/{candidate_name}"
            try:
                return self.create(user_id, rel, content)
            except AppError as exc:
                if exc.status_code != 409:
                    raise
            index += 1

    def create_dir(self, user_id: int, rel: str) -> None:
        home = self.ensure_home(user_id)
        directory = guard(home, rel)
        try:
            directory.mkdir(parents=True, exist_ok=True)
        except OSError as exc:
            raise _io_error(f"新建文件夹失败：{rel}") from exc

    def rename(self, user_id: int, from_rel: str | None, to_rel: str | None) -> None:
        if not from_rel or not from_rel.strip() or not to_rel or not to_rel.strip():
            raise BadRequest("重命名需要提供 from 与 to")
        if from_rel == UNCLASSIFIED:
            raise BadRequest(f"「{UNCLASSIFIED}」是系统文件夹，不能改名")
        home = self.ensure_home(user_id)
        source = guard(home, from_rel)
        target = guard(home, to_rel)
        if not source.exists():
            raise NotFound(f"原路径不存在：{from_rel}")
        source_is_file = not source.is_dir()
        if source_is_file:
            require_note_extension(from_rel)
            require_note_extension(to_rel)
        elif to_rel.endswith(".md"):
            raise BadRequest("文件夹不能命名为 .md 笔记文件")
        if from_rel == to_rel:
            return
        if os.path.lexists(target):
            raise _conflict(f"目标位置已存在：{to_rel}")
        try:
            parent = target.parent
            if parent is not None and not parent.is_dir():
                parent.mkdir(parents=True, exist_ok=True)
            move_within(source, target)
        except OSError as exc:
            raise _io_error(f"重命名失败：{from_rel} → {to_rel}") from exc

    # ---------- 删除与回收站 ----------

    def delete_file(self, user_id: int, rel: str) -> None:
        require_note_extension(rel)
        home = self.ensure_home(user_id)
        file = guard(home, rel)
        if not file.exists():
            raise NotFound(f"笔记不存在：{rel}")
        if file.is_dir():
            raise BadRequest(f"「{rel}」是文件夹，请删除文件夹")
        self._trash_item(home, file, rel, "file")

    def delete_dir_to_trash(self, user_id: int, rel: str) -> None:
        if rel == UNCLASSIFIED:
            raise BadRequest(f"「{UNCLASSIFIED}」是系统文件夹，不能删除")
        home = self.ensure_home(user_id)
        directory = self._require_dir(home, rel)
        self._trash_item(home, directory, rel, "dir")

    def delete_dir_flatten(self, user_id: int, rel: str) -> None:
        if rel == UNCLASSIFIED:
            raise BadRequest(f"「{UNCLASSIFIED}」是系统文件夹，不能删除")
        home = self.ensure_home(user_id)
        directory = self._require_dir(home, rel)
        try:
            unclassified = self.ensure_unclassified(home)
            # 先记下再移，避免遍历中目录被修改（对应 Java 同名逻辑）
            markdown_files: list[Path] = []
            for current, _dirs, files in os.walk(directory, followlinks=False):
                for file_name_ in files:
                    candidate = Path(current) / file_name_
                    if candidate.name.lower().endswith(".md") and candidate.is_file():
                        markdown_files.append(candidate)
            markdown_files.sort(key=lambda item: str(item))
            for source_file in markdown_files:
                target = unique_target(unclassified, source_file.name)
                move_within(source_file, target)
            delete_tree(directory)
        except OSError as exc:
            raise _io_error(f"删除文件夹（笔记移入未分类）失败：{rel}") from exc

    def list_trash(self, user_id: int) -> list[views.TrashView]:
        home = self.home_dir(user_id)
        try:
            self.purge_trash_home(home)
            trash = home / TRASH_DIR
            if not trash.is_dir():
                return []
            result: list[views.TrashView] = []
            for entry_dir in sorted(trash.iterdir(), key=lambda item: str(item)):
                if not entry_dir.is_dir():
                    continue
                meta = read_entry_meta(entry_dir)
                if meta is None:
                    continue
                original_path, kind, deleted_at = meta
                data = entry_data_path(entry_dir, kind)
                if not os.path.lexists(data):
                    # 数据丢失的坏条目静默清理
                    delete_tree(entry_dir)
                    continue
                result.append(
                    views.TrashView(entry_dir.name, original_path, file_name(original_path), kind, deleted_at)
                )
            result.sort(key=lambda view: view.deletedAt, reverse=True)
            return result
        except OSError as exc:
            raise _io_error("读取回收站失败") from exc

    def restore(self, user_id: int, trash_id: str) -> None:
        home = self.ensure_home(user_id)
        entry_dir = self._require_trash_entry(home, trash_id)
        meta = read_entry_meta(entry_dir)
        if meta is None:
            raise BadRequest(f"回收站条目无效：{trash_id}")
        original_path, kind, _deleted_at = meta
        try:
            data = entry_data_path(entry_dir, kind)
            if not os.path.lexists(data):
                delete_tree(entry_dir)
                raise NotFound("回收站条目已失效（文件丢失）")
            target = self._pick_restore_target(home, original_path, kind == "dir")
            if kind == "dir":
                target.parent.mkdir(parents=True, exist_ok=True)
            move_within(data, target)
            delete_tree(entry_dir)
        except AppError:
            raise
        except OSError as exc:
            raise _io_error(f"恢复失败：{trash_id}") from exc

    def delete_trash_entry(self, user_id: int, trash_id: str) -> None:
        home = self.home_dir(user_id)
        entry_dir = self._require_trash_entry(home, trash_id)
        try:
            delete_tree(entry_dir)
        except OSError as exc:
            raise _io_error("删除回收站条目失败") from exc

    def clear_trash(self, user_id: int) -> None:
        home = self.home_dir(user_id)
        try:
            self.purge_trash_home(home)
            trash = home / TRASH_DIR
            if trash.is_dir():
                delete_tree(trash)
        except OSError as exc:
            raise _io_error("清空回收站失败") from exc

    # ---------- 清理 ----------

    def purge_trash_home(self, home: Path) -> int:
        """清理指定用户回收站中已过期/损坏的条目，返回删除条目数。"""
        trash = home / TRASH_DIR
        if not trash.is_dir():
            return 0
        cutoff = now_ms() - _retention_ms()
        removed = 0
        for entry_dir in sorted(trash.iterdir(), key=lambda item: str(item)):
            if not entry_dir.is_dir():
                continue
            meta = read_entry_meta(entry_dir)
            if meta is None or meta[2] < cutoff:
                delete_tree(entry_dir)
                removed += 1
        return removed

    def purge_all_expired(self, db: object | None = None) -> int:
        """清理所有用户的过期回收站（供定时任务）。

        ``db`` 仅用于兼容 `app/jobs/scheduler.py` 的调用签名，笔记存储不依赖数据库。
        """
        root = self.root
        if not root.is_dir():
            return 0
        removed = 0
        try:
            for child in sorted(root.iterdir(), key=lambda item: str(item)):
                if child.is_dir() and child.name.startswith("user-"):
                    removed += self.purge_trash_home(child)
        except OSError as exc:
            raise _io_error("回收站定时清理失败") from exc
        return removed

    # ---------- 内部 ----------

    def _require_dir(self, home: Path, rel: str) -> Path:
        directory = guard(home, rel)
        if not directory.exists():
            raise NotFound(f"文件夹不存在：{rel}")
        if not directory.is_dir():
            raise BadRequest(f"「{rel}」不是文件夹")
        return directory

    def _trash_item(self, home: Path, source: Path, original_rel: str, kind: str) -> None:
        try:
            trash = home / TRASH_DIR
            trash.mkdir(parents=True, exist_ok=True)
            entry_dir = trash / str(uuid.uuid4())
            entry_dir.mkdir(parents=True, exist_ok=True)
            # 先移动数据，再写元数据（数据已安全迁移到回收站目录）
            data = entry_data_path(entry_dir, kind)
            move_within(source, data)
            write_entry_meta(entry_dir, original_rel, kind)
        except OSError as exc:
            raise _io_error(f"移入回收站失败：{original_rel}") from exc

    def _require_trash_entry(self, home: Path, trash_id: str) -> Path:
        if trash_id is None or not _TRASH_ID_RE.fullmatch(trash_id):
            raise BadRequest("回收站条目编号非法")
        trash = home / TRASH_DIR
        entry_dir = Path(os.path.normpath(trash / trash_id))
        if not entry_dir.is_relative_to(Path(os.path.normpath(trash))):
            raise BadRequest("回收站条目编号非法")
        if not entry_dir.is_dir():
            raise NotFound(f"回收站条目不存在：{trash_id}")
        return entry_dir

    def _pick_restore_target(self, home: Path, original_rel: str, is_dir: bool) -> Path:
        """原父目录仍在且未被占用 → 原路径；否则进「未分类」，重名加 (n)。"""
        name = file_name(original_rel)
        if "/" in original_rel:
            parent_rel = original_rel[: original_rel.rfind("/")]
            parent = home / parent_rel
            candidate = parent / name
            if parent.is_dir() and not os.path.lexists(candidate):
                return candidate
        else:
            candidate = home / name
            if not os.path.lexists(candidate):
                return candidate
        unclassified = self.ensure_unclassified(home)
        return unique_target(unclassified, name)


_default_service: NotesService | None = None


def get_notes_service() -> NotesService:
    """进程内默认 NotesService（根目录动态读 settings，便于测试覆盖）。"""
    global _default_service
    if _default_service is None:
        _default_service = NotesService()
    return _default_service
