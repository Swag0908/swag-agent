"""技能注册表：内置 + 外部目录扫描、热插拔、启停落库。

对齐 Java `SkillRegistry` / `JdbcSkillStateStore`：
- 内置目录：仓库内 `swag_agent_backend/src/main/resources/skills/<name>/SKILL.md`（当前无目录）；
- 外部目录：`settings.skills_root_path`（默认 ./skills-data），同名覆盖内置；
- 外部根目录 mtime 变化时下次读取自动重扫；
- 启停状态存 `skill_state`：没有行 = 启用；技能目录消失时清理状态行（列表为空时不清理）。
"""

from __future__ import annotations

import logging
import shutil
import threading
from dataclasses import dataclass
from pathlib import Path

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.config import settings
from app.core.timeutil import now
from app.db.models import SkillState
from app.skills.markdown import parse

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class SkillManifest:
    """一个已发现的技能清单；file_path 便于管理端排查来源。"""

    name: str
    description: str
    body: str
    external: bool
    file_path: str

    @property
    def source(self) -> str:
        """来源标识：builtin（随包发布）/ external（运行时安装）。"""
        return "external" if self.external else "builtin"


def default_builtin_root() -> Path:
    """仓库内与 Java classpath 对应的内置技能目录。

    app/skills/registry.py → parents[0]=app/skills, [1]=app, [2]=swag_agent_backend_py,
    [3]=仓库根。打包部署（只带 Python 后端）时目录不存在，扫描结果为空即可。
    """
    try:
        repo_root = Path(__file__).resolve().parents[3]
        return repo_root / "swag_agent_backend" / "src" / "main" / "resources" / "skills"
    except IndexError:  # pragma: no cover - 理论上不会发生
        return Path("skills")


class SkillRegistry:
    """进程内技能注册表（线程安全）。方法接受 db 以读写 skill_state。"""

    def __init__(self, external_root: Path | str | None = None, builtin_root: Path | str | None = None) -> None:
        self._external_root = (
            Path(external_root).expanduser().resolve() if external_root is not None else settings.skills_root_path
        )
        self._builtin_root = (
            Path(builtin_root).expanduser().resolve() if builtin_root is not None else default_builtin_root()
        )
        self._manifests: dict[str, SkillManifest] = {}
        self._external_stamp: int | None = None
        self._scanned = False
        self._lock = threading.RLock()

    # ------------------------------------------------------------------
    # 对外查询
    # ------------------------------------------------------------------

    @property
    def external_root(self) -> Path:
        return self._external_root

    @property
    def builtin_root(self) -> Path:
        return self._builtin_root

    def list(self, db: Session | None = None) -> list[SkillManifest]:
        with self._lock:
            self._refresh_if_changed(db)
            return sorted(self._manifests.values(), key=lambda manifest: manifest.name)

    def enabled(self, db: Session) -> list[SkillManifest]:
        disabled = self.disabled_names(db)
        return [manifest for manifest in self.list(db) if manifest.name not in disabled]

    def find(self, name: str) -> SkillManifest | None:
        with self._lock:
            self._refresh_if_changed()
            return self._manifests.get(name)

    def is_enabled(self, db: Session, name: str) -> bool:
        with self._lock:
            self._refresh_if_changed(db)
            if name not in self._manifests:
                return False
            return name not in self.disabled_names(db)

    def disabled_names(self, db: Session) -> set[str]:
        """skill_state 里 enabled=0 的技能名；缺行视为启用。"""
        names = db.scalars(select(SkillState.skill_name).where(SkillState.enabled.is_(False))).all()
        return {str(name) for name in names}

    def set_enabled(self, db: Session, name: str, enabled: bool) -> bool:
        with self._lock:
            self._refresh_if_changed(db)
            if name not in self._manifests:
                return False
            self._write_state(db, name, enabled)
            return True

    def delete_external(self, db: Session, name: str) -> bool:
        with self._lock:
            self._refresh_if_changed(db)
            manifest = self._manifests.get(name)
            if manifest is None or not manifest.external:
                return False
            directory = Path(manifest.file_path).resolve().parent
            try:
                directory.relative_to(self._external_root)
            except ValueError:
                return False
            shutil.rmtree(directory, ignore_errors=False)
            self._delete_state(db, name)
            self.refresh(db)
            return True

    def refresh(self, db: Session | None = None) -> None:
        with self._lock:
            found: dict[str, SkillManifest] = {}
            builtin = self._scan(self._builtin_root, external=False)
            external = self._scan(self._external_root, external=True)
            for manifest in builtin:
                found[manifest.name] = manifest
            # 外部同名覆盖内置（便于不改代码覆盖技能）。
            for manifest in external:
                found[manifest.name] = manifest
            self._manifests = found
            # 已被删除的技能不再保留历史启停状态；列表为空时不清理（避免扫描异常误删）。
            if db is not None and found:
                self._remove_missing_state(db, set(found))
            self._external_stamp = self._current_external_stamp()
            self._scanned = True
            logger.info("技能注册表刷新完成：共 %s 个（内置 %s / 外部 %s）", len(found), len(builtin), len(external))

    # ------------------------------------------------------------------
    # 内部：扫描与状态
    # ------------------------------------------------------------------

    def _refresh_if_changed(self, db: Session | None = None) -> None:
        if not self._scanned or self._current_external_stamp() != self._external_stamp:
            self.refresh(db)

    def _current_external_stamp(self) -> int | None:
        try:
            if self._external_root.is_dir():
                return self._external_root.stat().st_mtime_ns
        except OSError:
            return None
        return None

    def _scan(self, root: Path, *, external: bool) -> list[SkillManifest]:
        if not root.is_dir():
            return []
        manifests: list[SkillManifest] = []
        for directory in sorted(root.iterdir()):
            if not directory.is_dir() or directory.name.startswith("."):
                continue
            skill_file = directory / "SKILL.md"
            if not skill_file.is_file():
                continue
            try:
                raw = skill_file.read_text(encoding="utf-8")
            except (OSError, UnicodeDecodeError) as exc:
                logger.warning("读取技能失败：%s（%s）", skill_file, exc)
                continue
            result = parse(directory.name, raw)
            if not result.ok or result.parsed is None:
                logger.warning("跳过无效技能 %s：%s", skill_file, result.error)
                continue
            manifests.append(
                SkillManifest(
                    name=result.parsed.name,
                    description=result.parsed.description,
                    body=result.parsed.body,
                    external=external,
                    file_path=str(skill_file),
                )
            )
        return manifests

    def _write_state(self, db: Session, name: str, enabled: bool) -> None:
        row = db.get(SkillState, name)
        updated_at = now()  # skill_state 是 DATETIME(6)，保留微秒
        if row is None:
            db.add(SkillState(skill_name=name, enabled=bool(enabled), updated_at=updated_at))
        else:
            row.enabled = bool(enabled)
            row.updated_at = updated_at
        db.commit()

    def _delete_state(self, db: Session, name: str) -> None:
        db.execute(delete(SkillState).where(SkillState.skill_name == name))
        db.commit()

    def _remove_missing_state(self, db: Session, existing_names: set[str]) -> None:
        if not existing_names:
            return
        db.execute(delete(SkillState).where(SkillState.skill_name.not_in(existing_names)))
        db.commit()


# ---------------------------------------------------------------------------
# 进程内单例（测试可 monkeypatch `_instance`）
# ---------------------------------------------------------------------------

_instance: SkillRegistry | None = None
_instance_lock = threading.Lock()


def get_registry() -> SkillRegistry:
    global _instance
    if _instance is None:
        with _instance_lock:
            if _instance is None:
                _instance = SkillRegistry()
    return _instance


def reset_registry() -> None:
    """测试用：丢弃进程内注册表缓存（下次 get_registry 重新按 settings 构建）。"""
    global _instance
    with _instance_lock:
        _instance = None
