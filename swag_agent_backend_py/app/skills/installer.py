"""技能安装器：git clone --depth 1 到临时目录 → 定位含 SKILL.md 的目录 → 复制到外部根目录。

对齐 Java `SkillInstaller`：支持 owner/repo 简写、https/http、git@/ssh；60 秒超时；
只拷贝技能目录（去掉 .git），同名先删后拷，防目录逃逸；禁用时 403。
"""

from __future__ import annotations

import logging
import os
import re
import shutil
import subprocess
import tempfile
from pathlib import Path

from sqlalchemy.orm import Session

from app.config import settings
from app.core.errors import AppError, BadRequest, Forbidden
from app.skills.markdown import parse
from app.skills.registry import SkillRegistry, get_registry

logger = logging.getLogger(__name__)

# GitHub 简写 owner/repo（与 Java SkillInstaller.SHORTHAND 等价）。
_SHORTHAND = re.compile(r"[A-Za-z0-9][\w.-]*/[\w.-]+")
_CANDIDATE_SCAN_DEPTH = 4
_CANDIDATE_LIMIT = 20

__all__ = ["install", "normalize_repo_url", "resolve_source", "copy_skills", "find_skill_candidates"]


def install(
    repo_url: str | None,
    skill_path: str | None,
    *,
    registry: SkillRegistry | None = None,
    db: Session | None = None,
) -> list[str]:
    """安装并返回已安装（覆盖安装也算）的技能目录名。"""
    if not settings.skills_install_enabled:
        raise Forbidden("技能安装功能已关闭（app.skills.install-enabled=false）")

    url = normalize_repo_url(repo_url)
    target_registry = registry or get_registry()
    root = target_registry.external_root
    temp: Path | None = None
    try:
        logger.info("开始安装技能：repo=%s, skillPath=%s", url, skill_path or "<auto>")
        root.mkdir(parents=True, exist_ok=True)
        # git clone 允许目标目录已存在且为空，因此 temp 直接作为 clone 目录。
        temp = Path(tempfile.mkdtemp(prefix="swag-skill-"))
        _git_clone(url, temp)
        source = resolve_source(temp, skill_path)
        installed = copy_skills(source, root)
        if not installed:
            path_hint = f"：{skill_path}" if skill_path and skill_path.strip() else ""
            candidates = find_skill_candidates(temp)
            candidate_hint = (
                "；仓库内可选的技能路径（用 skillPath 指定）：" + "、".join(candidates) if candidates else ""
            )
            raise BadRequest("仓库中没有找到含 SKILL.md 的技能目录" + path_hint + candidate_hint)
        target_registry.refresh(db)
        logger.info("技能安装完成：%s -> %s", url, installed)
        return installed
    except AppError:
        raise
    except OSError as exc:
        logger.exception("技能安装遇到文件系统错误：repo=%s", url)
        raise AppError(500, f"安装技能失败：{exc}") from exc
    finally:
        if temp is not None:
            shutil.rmtree(temp, ignore_errors=True)


def normalize_repo_url(repo_url: str | None) -> str:
    """把用户给的写法规范成 git 可识别地址；非法输入 400。"""
    if repo_url is None or not repo_url.strip():
        raise BadRequest("repoUrl 不能为空")
    url = repo_url.strip()
    # 防参数注入：绝不允许以 - 开头。
    if url.startswith("-"):
        raise BadRequest(f"repoUrl 非法：{repo_url}")
    if _SHORTHAND.fullmatch(url):
        return "https://github.com/" + url + ".git"
    if url.startswith(("https://", "http://", "git@", "ssh://")):
        return url
    raise BadRequest(f"repoUrl 只支持 https://、ssh://、git@ 或 owner/repo 简写：{repo_url}")


def _git_clone(url: str, target: Path) -> None:
    env = dict(os.environ)
    env["GIT_TERMINAL_PROMPT"] = "0"
    timeout = max(1, settings.skills_install_timeout_seconds)
    command = ["git", "clone", "--depth", "1", url, str(target)]
    try:
        completed = subprocess.run(
            command,
            capture_output=True,
            text=True,
            errors="replace",
            timeout=timeout,
            env=env,
            check=False,
        )
    except FileNotFoundError as exc:
        logger.error("无法启动 git clone：repo=%s", url)
        raise AppError(500, f"无法执行 git，请确认后端所在机器已安装 git：{exc}") from exc
    except subprocess.TimeoutExpired as exc:
        raise AppError(504, f"git clone 超时（{timeout} 秒）：{url}") from exc
    if completed.returncode != 0:
        output = (completed.stdout or "") + (completed.stderr or "")
        logger.warning("git clone 失败：repo=%s, exit=%s, output=%s", url, completed.returncode, _tail(output))
        raise BadRequest("git clone 失败：" + _tail(output))


def resolve_source(clone_dir: Path, skill_path: str | None) -> Path:
    """定位仓库内技能目录；skillPath 不能逃出 clone 目录。"""
    if skill_path is None or not skill_path.strip():
        return clone_dir
    raw = skill_path.strip()
    if Path(raw).is_absolute():
        raise BadRequest(f"skillPath 非法：{skill_path}")
    candidate = Path(os.path.normpath(str(clone_dir / raw)))
    try:
        candidate.relative_to(Path(os.path.normpath(str(clone_dir))))
    except ValueError as exc:
        raise BadRequest(f"skillPath 非法：{skill_path}") from exc
    if not candidate.is_dir():
        raise BadRequest(f"仓库中不存在目录：{skill_path}")
    return candidate


def copy_skills(source: Path, root: Path) -> list[str]:
    """拷贝技能目录（同名覆盖）；返回目录名列表。"""
    if (source / "SKILL.md").is_file():
        skill_dirs = [source]
    else:
        skill_dirs = sorted(
            directory
            for directory in source.iterdir()
            if directory.is_dir()
            and not directory.name.startswith(".")
            and (directory / "SKILL.md").is_file()
        )

    installed: list[str] = []
    root_resolved = root.resolve()
    for directory in skill_dirs:
        folder_name = _target_folder_name(directory)
        target = root / folder_name
        try:
            target.resolve().relative_to(root_resolved)
        except ValueError:
            logger.warning("跳过非法技能目录名：%s", folder_name)
            continue
        if target.exists():
            shutil.rmtree(target)
        shutil.copytree(directory, target, ignore=shutil.ignore_patterns(".git"))
        installed.append(folder_name)
    return installed


def _target_folder_name(skill_dir: Path) -> str:
    """目录名优先取 frontmatter name；解析失败退回原目录名（Java 同）。"""
    try:
        raw = (skill_dir / "SKILL.md").read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return skill_dir.name
    result = parse(skill_dir.name, raw)
    if result.ok and result.parsed is not None:
        return result.parsed.name
    return skill_dir.name


def find_skill_candidates(root: Path) -> list[str]:
    """有界深度查找含 SKILL.md 的目录，用于安装失败时提示可用 skillPath。"""
    candidates: list[str] = []
    for directory in sorted(root.rglob("SKILL.md")):
        skill_dir = directory.parent
        try:
            relative = skill_dir.relative_to(root)
        except ValueError:
            continue
        if not relative.parts or ".git" in relative.parts:
            continue
        if len(relative.parts) > _CANDIDATE_SCAN_DEPTH:
            continue
        candidates.append(relative.as_posix())
        if len(candidates) >= _CANDIDATE_LIMIT:
            break
    return candidates


def _tail(output: str | None) -> str:
    flat = (output or "").strip()
    if len(flat) <= 500:
        return flat
    return "…" + flat[-500:]
