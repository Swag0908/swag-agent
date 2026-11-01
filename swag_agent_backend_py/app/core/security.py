"""密码哈希与 token 生成。"""

from __future__ import annotations

import uuid

import bcrypt


def hash_password(password: str) -> str:
    """用 BCrypt 加盐生成密码哈希；数据库保存哈希，不保存明文密码。"""
    return bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")


def verify_password(password: str, password_hash: str) -> bool:
    """检查输入密码是否与哈希匹配；空输入或损坏的哈希返回 False。"""
    if not password or not password_hash:
        return False
    try:
        return bcrypt.checkpw(password.encode("utf-8"), password_hash.encode("utf-8"))
    except ValueError:
        return False


def new_token() -> str:
    """生成随机 UUID 登录令牌；有效期和归属另存 auth_token 表，不是 JWT。"""
    return str(uuid.uuid4())


def new_id() -> str:
    """生成随机 UUID 标识，供需要字符串主键的记录使用。"""
    return str(uuid.uuid4())
