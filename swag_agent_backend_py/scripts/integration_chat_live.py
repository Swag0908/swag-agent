#!/usr/bin/env python3
"""真实 DeepSeek 单轮冒烟：不带 conversationId，因此不写业务表；审计关闭。

验证：鉴权 -> 提示词/记忆降级 -> DeepSeek 流式 -> 工具循环 -> 7 类 SSE 事件。
会消耗一次极小的模型调用（用户 key）。运行：
    AUDIT_ENABLED=false .venv/bin/python scripts/integration_chat_live.py
"""

from __future__ import annotations

import json
import os
import sys
import time
import uuid
from datetime import timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
os.environ.setdefault("AUDIT_ENABLED", "false")

from fastapi.testclient import TestClient  # noqa: E402

from app.core.timeutil import now  # noqa: E402
from app.db.base import SessionLocal  # noqa: E402
from app.db.models import AuthToken  # noqa: E402
from app.main import app  # noqa: E402


def main() -> int:
    with SessionLocal() as db:
        token = str(uuid.uuid4())
        db.add(AuthToken(token=token, user_id=1, expires_at=now() + timedelta(minutes=10), created_at=now()))
        db.commit()
    headers = {"Authorization": f"Bearer {token}"}
    counts: dict[str, int] = {}
    events: list[tuple[str, dict]] = []
    started = time.monotonic()
    first_event_at = None
    try:
        with TestClient(app) as client:
            with client.stream(
                "GET",
                "/test/chat/stream/events",
                params={"model": 1, "userInput": "现在几点？只回答时间。"},
                headers=headers,
            ) as response:
                print("http", response.status_code, response.headers.get("content-type"))
                if response.status_code != 200:
                    print(response.read().decode("utf-8", "replace")[:500])
                    return 1
                event_name = None
                for line in response.iter_lines():
                    if line.startswith("event:"):
                        event_name = line.split(":", 1)[1].strip()
                        counts[event_name] = counts.get(event_name, 0) + 1
                        if first_event_at is None:
                            first_event_at = time.monotonic() - started
                    elif line.startswith("data:"):
                        raw = line.split(":", 1)[1].strip()
                        try:
                            payload = json.loads(raw)
                        except json.JSONDecodeError:
                            payload = {"raw": raw}
                        events.append((event_name or "?", payload))
                        # Python 新格式是扁平 payload；兼容旧 Java 的 {"type","data"} 包装。
                        data = payload.get("data", payload)
                        if event_name in {"content", "reasoning"}:
                            print(f"  {event_name}: {data.get('text', '')!r}")
                        elif event_name == "tool_call":
                            print(f"  tool_call: {data}")
                        elif event_name in {"ready", "error", "segment_boundary", "done"}:
                            print(f"  {event_name}: {data}")
    finally:
        with SessionLocal() as db:
            db.query(AuthToken).filter(AuthToken.token == token).delete()
            db.commit()

    elapsed = time.monotonic() - started
    print("\nevent counts:", counts)
    print(f"first event after {first_event_at:.3f}s, total {elapsed:.2f}s")
    if "done" in counts and counts.get("error", 0) == 0:
        print("LIVE CHAT OK")
        return 0
    print("LIVE CHAT FAILED (see error event above)")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
