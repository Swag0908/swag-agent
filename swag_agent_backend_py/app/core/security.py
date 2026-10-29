"""密码哈希与 token 生成。"""

from __future__ import annotations

import uuid

import bcrypt


def hash_password(password: str) -> str:
    return bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")


def verify_password(password: str, password_hash: str) -> bool:
    if not password or not password_hash:
        return False
    try:
        return bcrypt.checkpw(password.encode("utf-8"), password_hash.encode("utf-8"))
    except ValueError:
        return False


def new_token() -> str:
    return str(uuid.uuid4())


def new_id() -> str:
    return str(uuid.uuid4())
