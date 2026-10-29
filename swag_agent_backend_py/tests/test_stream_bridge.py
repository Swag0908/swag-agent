"""流式桥语义测试：全部用 fake chunk，不调用真实 DeepSeek。

覆盖（对照 Java `ChatStreamBridgeTests` / `ToolEventRelayTests`）：
1. 不用工具 → 只有 content；
2. 工具后回答转正 + 工具前铺垫降级（segment_boundary{final_answer}）；
3. 只调工具不说话 → 正文为空 + segment_boundary{tool_only}；
4. 工具事件成对（RUNNING→SUCCEEDED/FAILED，同 call_id，带 duration_ms）；
5. 事件增量下发（不是攒完再吐）；
6. 工具抛异常 → FAILED 且流不炸；
7. 危险工具需确认 → error 事件（SSE）或向上抛（非流式）；
8. max_tool_rounds 护栏；
9. SSE 帧格式（event:/data:/空行、单行 JSON、type==事件名）。
"""

from __future__ import annotations

import asyncio
import json
import time
from dataclasses import dataclass, field
from datetime import timedelta
from typing import Any

import pytest

from app.agent.stream import events
from app.agent.stream import bridge as bridge_module
from app.agent.stream.bridge import TurnState, stream_turn
from app.agent.tools import registry
from app.agent.tools.registry import ToolCtx
from app.core.errors import ConfirmationRequired
from app.core.timeutil import now

USER = ToolCtx(user_id=7)


# ---------------------------------------------------------------------------
# fake 流：形状与 openai SDK chunk 一致
# ---------------------------------------------------------------------------


@dataclass
class FakeFunction:
    name: str | None = None
    arguments: str | None = None


@dataclass
class FakeToolCall:
    index: int
    id: str | None = None
    type: str = "function"
    function: FakeFunction | None = None


@dataclass
class FakeDelta:
    content: str | None = None
    tool_calls: list[FakeToolCall] | None = None
    reasoning_content: str | None = None


@dataclass
class FakeChoice:
    delta: FakeDelta
    finish_reason: str | None = None


@dataclass
class FakeChunk:
    choices: list[FakeChoice] = field(default_factory=list)


def text_chunk(text: str) -> FakeChunk:
    return FakeChunk([FakeChoice(FakeDelta(content=text))])


def reasoning_chunk(text: str) -> FakeChunk:
    return FakeChunk([FakeChoice(FakeDelta(reasoning_content=text))])


def tool_chunk(index: int, call_id: str, name: str, arguments: str) -> FakeChunk:
    return FakeChunk(
        [
            FakeChoice(
                FakeDelta(
                    tool_calls=[
                        FakeToolCall(index=index, id=call_id, function=FakeFunction(name=name, arguments=arguments))
                    ]
                )
            )
        ]
    )


def finish_chunk(reason: str = "stop") -> FakeChunk:
    return FakeChunk([FakeChoice(FakeDelta(), finish_reason=reason)])


class ScriptedStream:
    """每被调用一次消费一轮 chunk；记录每轮收到的 messages 快照。"""

    def __init__(self, rounds: list[list[FakeChunk]], delay: float = 0.0) -> None:
        self.rounds = list(rounds)
        self.delay = delay
        self.calls = 0
        self.snapshots: list[list[dict[str, Any]]] = []

    def __call__(self, messages: list[dict[str, Any]], model: str):
        index = self.calls
        self.calls += 1
        self.snapshots.append([dict(message) for message in messages])
        chunks = self.rounds[index] if index < len(self.rounds) else []
        return self._gen(chunks)

    async def _gen(self, chunks: list[FakeChunk]):
        for chunk in chunks:
            if self.delay:
                await asyncio.sleep(self.delay)
            yield chunk


async def collect(factory: ScriptedStream, **kwargs) -> list[events.SseEvent]:
    state = kwargs.pop("state", TurnState())
    generator = stream_turn(
        [{"role": "user", "content": "hi"}],
        "deepseek-v4-flash",
        kwargs.pop("ctx", USER),
        stream_factory=factory,
        state=state,
        **kwargs,
    )
    return [event async for event in generator]


def names(events_list: list[events.SseEvent]) -> list[str]:
    return [event.name for event in events_list]


def payloads(events_list: list[events.SseEvent], name: str) -> list[dict[str, Any]]:
    return [event.data for event in events_list if event.name == name]


@pytest.fixture()
def fake_echo_tool():
    """注册一个测试工具并自动清理（避免污染全局 REGISTRY）。"""
    calls: list[tuple[str, int | None]] = []

    @registry.tool(
        "fakeEcho",
        "测试回声工具。第二句不应出现在兜底文案里。",
        {
            "type": "object",
            "properties": {"query": {"type": "string", "description": "关键词"}},
            "required": ["query"],
        },
    )
    async def fake_echo(query: str, ctx: ToolCtx) -> str:
        calls.append((query, ctx.user_id))
        return f"echo:{query}"

    try:
        yield calls
    finally:
        registry.REGISTRY.pop("fakeEcho", None)


# ---------------------------------------------------------------------------
# 1) 不用工具
# ---------------------------------------------------------------------------


async def test_no_tool_answer_streams_content():
    factory = ScriptedStream([[text_chunk("你好，"), text_chunk("我是助手。"), finish_chunk("stop")]])
    state = TurnState()
    result = await collect(factory, state=state)

    assert names(result) == ["ready", "content", "content", "done"]
    assert payloads(result, "content") == [{"text": "你好，"}, {"text": "我是助手。"}]
    assert result[0].data == {"conversation_id": None}
    assert result[-1].data == {}
    assert state.final_answer == "你好，我是助手。"
    assert not state.has_tool_events
    # 单轮、无需第二轮
    assert factory.calls == 1


# ---------------------------------------------------------------------------
# 2) 工具后的回答转正、工具前铺垫降级
# ---------------------------------------------------------------------------


async def test_answer_after_tool_becomes_content_and_pre_tool_text_is_demoted(fake_echo_tool):
    factory = ScriptedStream(
        [
            [
                text_chunk("我先查一下。"),
                tool_chunk(0, "call_1", "fakeEcho", '{"query":"x"}'),
                finish_chunk("tool_calls"),
            ],
            [text_chunk("现在是下午三点。"), finish_chunk("stop")],
        ]
    )
    state = TurnState()
    result = await collect(factory, state=state, conversation_id=12)

    name_list = names(result)
    assert name_list[0] == "ready"
    assert name_list[-1] == "done"
    assert result[0].data == {"conversation_id": 12}

    # 工具前的铺垫先按 content 发出（当时无法预知），收尾时用 segment_boundary 降级
    contents = [event.data["text"] for event in result if event.name == "content"]
    assert contents[0] == "我先查一下。"
    assert contents[-1] == "现在是下午三点。"

    boundaries = payloads(result, "segment_boundary")
    assert boundaries == [{"reason": "final_answer"}]
    boundary_index = name_list.index("segment_boundary")
    assert name_list.index("content", boundary_index) == len(name_list) - 2  # 边界的下一条就是转正 content

    # 工具后文字实时走 reasoning（只展示、不落库）
    assert [event.data["text"] for event in result if event.name == "reasoning"] == ["现在是下午三点。"]

    # 落库回答 = 工具后那段，不是铺垫
    assert state.final_answer == "现在是下午三点。"
    assert fake_echo_tool == [("x", 7)]

    # 第二轮请求带上了 assistant(tool_calls) 与 tool 结果
    second_round = factory.snapshots[1]
    assert second_round[-2]["role"] == "assistant"
    assert second_round[-2]["tool_calls"][0]["id"] == "call_1"
    assert second_round[-1] == {"role": "tool", "tool_call_id": "call_1", "content": "echo:x"}


# ---------------------------------------------------------------------------
# 3) 只调工具、不说话
# ---------------------------------------------------------------------------


async def test_tool_only_leaves_answer_empty(fake_echo_tool):
    factory = ScriptedStream(
        [
            [
                text_chunk("我先查一下。"),
                tool_chunk(0, "call_9", "fakeEcho", '{"query":"y"}'),
                finish_chunk("tool_calls"),
            ],
            [finish_chunk("stop")],
        ]
    )
    state = TurnState()
    result = await collect(factory, state=state)

    boundaries = payloads(result, "segment_boundary")
    assert boundaries == [{"reason": "tool_only"}]
    # 转正为空：segment_boundary 之后不再有 content，正文最终为空
    boundary_index = names(result).index("segment_boundary")
    assert "content" not in names(result)[boundary_index:]
    assert state.final_answer == ""


# ---------------------------------------------------------------------------
# 4) 工具事件成对 + duration_ms
# ---------------------------------------------------------------------------


async def test_tool_events_are_paired_with_call_id_and_duration(fake_echo_tool):
    factory = ScriptedStream(
        [
            [tool_chunk(0, "call_a", "fakeEcho", '{"query":"hello"}'), finish_chunk("tool_calls")],
            [text_chunk("done"), finish_chunk("stop")],
        ]
    )
    result = await collect(factory)
    tool_events = payloads(result, "tool_call")
    assert len(tool_events) == 2

    running, succeeded = tool_events
    assert running["status"] == "RUNNING"
    assert succeeded["status"] == "SUCCEEDED"
    assert running["name"] == succeeded["name"] == "fakeEcho"
    assert running["call_id"] == succeeded["call_id"] == "call_a"
    assert running["display"].startswith("正在")
    assert running["detail"] == "hello"
    assert "duration_ms" not in running
    assert isinstance(succeeded["duration_ms"], int) and succeeded["duration_ms"] >= 0

    name_list = names(result)
    assert name_list.index("tool_call") < name_list.index("tool_call", name_list.index("tool_call") + 1)


# ---------------------------------------------------------------------------
# 5) 增量下发（不是攒完再吐）
# ---------------------------------------------------------------------------


async def test_events_are_incremental_not_buffered():
    factory = ScriptedStream(
        [[text_chunk("第一段。"), text_chunk("第二段。"), text_chunk("第三段。"), finish_chunk("stop")]],
        delay=0.05,
    )
    first_at: list[float] = []
    began = time.monotonic()

    async for _event in stream_turn(
        [{"role": "user", "content": "hi"}],
        "deepseek-v4-flash",
        USER,
        stream_factory=factory,
        state=TurnState(),
    ):
        if not first_at:
            first_at.append(time.monotonic() - began)
    total = time.monotonic() - began

    assert first_at and first_at[0] >= 0
    assert first_at[0] < total / 2, f"首条事件 {first_at[0]:.3f}s 应远小于整条流 {total:.3f}s"


# ---------------------------------------------------------------------------
# 6) 工具异常 → FAILED，流不炸
# ---------------------------------------------------------------------------


async def test_tool_exception_marks_failed_and_keeps_stream_alive():
    @registry.tool("fakeBoom", "会炸的工具。", {"type": "object", "properties": {}, "required": []})
    async def fake_boom(ctx: ToolCtx) -> str:
        raise RuntimeError("boom")

    try:
        factory = ScriptedStream(
            [
                [tool_chunk(0, "call_b", "fakeBoom", "{}"), finish_chunk("tool_calls")],
                [text_chunk("降级后的回答"), finish_chunk("stop")],
            ]
        )
        state = TurnState()
        result = await collect(factory, state=state)

        statuses = [event.data["status"] for event in result if event.name == "tool_call"]
        assert statuses == ["RUNNING", "FAILED"]
        tool_message = factory.snapshots[1][-1]
        assert tool_message["role"] == "tool" and "工具执行失败" in tool_message["content"]
        # 流没有被异常打断，仍给出最终回答
        assert state.final_answer == "降级后的回答"
        assert names(result)[-1] == "done"
    finally:
        registry.REGISTRY.pop("fakeBoom", None)


# ---------------------------------------------------------------------------
# 7) 危险工具确认
# ---------------------------------------------------------------------------


class _ConfirmingRecorder:
    def record_event(self, *args, **kwargs):  # noqa: ANN002, ANN003
        return None

    def record_tool_requested(self, tool_name, arguments, audit_id, user_id):  # noqa: ANN001
        return "call_conf"

    def check_tool_confirmation(self, tool_name, arguments, ctx):  # noqa: ANN001
        raise ConfirmationRequired(
            confirmation_id="11111111-1111-1111-1111-111111111111",
            audit_id="22222222-2222-2222-2222-222222222222",
            tool_name=tool_name,
            requested_at=now(),
            expires_at=now() + timedelta(minutes=10),
        )


async def test_confirmation_required_emits_failed_then_error(fake_echo_tool, monkeypatch):
    monkeypatch.setattr(bridge_module, "_audit_recorder", lambda: _ConfirmingRecorder())
    factory = ScriptedStream([[tool_chunk(0, "call_c", "fakeEcho", "{}"), finish_chunk("tool_calls")]])
    result = await collect(factory)

    name_list = names(result)
    assert "error" in name_list
    assert "done" not in name_list  # Java：异常时用单个 error 事件替换整条流
    statuses = [event.data["status"] for event in result if event.name == "tool_call"]
    assert statuses == ["RUNNING", "FAILED"]
    assert "confirmationId" in payloads(result, "error")[0]["message"]
    assert fake_echo_tool == []  # 没执行工具


async def test_confirmation_required_can_raise_for_non_stream(fake_echo_tool, monkeypatch):
    monkeypatch.setattr(bridge_module, "_audit_recorder", lambda: _ConfirmingRecorder())
    factory = ScriptedStream([[tool_chunk(0, "call_c", "fakeEcho", "{}"), finish_chunk("tool_calls")]])
    with pytest.raises(ConfirmationRequired):
        await collect(factory, on_confirmation="raise")


# ---------------------------------------------------------------------------
# 8) max_tool_rounds 护栏
# ---------------------------------------------------------------------------


async def test_max_tool_rounds_stops_infinite_tool_loop(fake_echo_tool):
    rounds = [
        [tool_chunk(0, f"call_{index}", "fakeEcho", '{"query":"loop"}'), finish_chunk("tool_calls")]
        for index in range(10)
    ]
    factory = ScriptedStream(rounds)
    state = TurnState()
    result = await collect(factory, state=state, max_rounds=3)

    assert factory.calls == 3
    assert names(result)[-1] == "done"
    # 每轮都调了工具、没说话 → 正文为空；本测试工具前没有正文，所以按 Java 规则
    # 不发 segment_boundary（有铺垫时才是 tool_only，见 test_tool_only_leaves_answer_empty）
    assert payloads(result, "segment_boundary") == []
    assert state.final_answer == ""


# ---------------------------------------------------------------------------
# 9) reasoning_content 回传（DeepSeek thinking + tools 的硬要求）
# ---------------------------------------------------------------------------


async def test_reasoning_content_is_passed_back_in_assistant_message(fake_echo_tool):
    factory = ScriptedStream(
        [
            [
                reasoning_chunk("思考中"),
                tool_chunk(0, "call_r", "fakeEcho", '{"query":"z"}'),
                finish_chunk("tool_calls"),
            ],
            [text_chunk("答案"), finish_chunk("stop")],
        ]
    )
    result = await collect(factory)
    assistant = factory.snapshots[1][-2]
    assert assistant["role"] == "assistant"
    assert assistant.get("reasoning_content") == "思考中"
    # 思维链不冒充 reasoning 事件（reasoning 只表示工具后的过渡文字）
    reasoning_texts = [event.data["text"] for event in result if event.name == "reasoning"]
    assert "思考中" not in reasoning_texts


# ---------------------------------------------------------------------------
# 10) SSE 帧格式
# ---------------------------------------------------------------------------


def test_sse_frame_format_and_omission_rules():
    frame = events.content("你好").encode()
    assert frame.startswith("event: content\ndata: ")
    assert frame.endswith("\n\n")
    body_line = frame.split("data: ", 1)[1].strip()
    assert "\n" not in body_line  # 单行 JSON
    payload = json.loads(body_line)
    # 前端 api/chat.js 直接读扁平 data.text，因此不能包 {"type":...,"data":{...}}。
    assert payload == {"text": "你好"}

    running = events.tool_call("webSearch", "RUNNING", "正在联网搜索：x", None, "call_1")
    assert running.data == {
        "name": "webSearch",
        "status": "RUNNING",
        "display": "正在联网搜索：x",
        "call_id": "call_1",
    }
    succeeded = events.tool_call("webSearch", "SUCCEEDED", "正在联网搜索：x", "x", "call_1", 12)
    assert succeeded.data["duration_ms"] == 12
    assert succeeded.data["detail"] == "x"

    assert events.done().encode() == 'event: done\ndata: {}\n\n'
    assert events.segment_boundary("tool_only").data == {"reason": "tool_only"}
    assert events.ready(3).data == {"conversation_id": 3}
    assert events.ready().data == {"conversation_id": None}


# ---------------------------------------------------------------------------
# 11) 模型流异常：SSE 发 error 不发 done；非流式则向上抛
# ---------------------------------------------------------------------------


class BoomStream:
    def __call__(self, messages, model):  # noqa: ANN001
        return self._gen()

    async def _gen(self):
        raise RuntimeError("upstream boom")
        yield  # pragma: no cover - 让函数成为 async generator


async def test_stream_error_emits_single_error_event_without_done():
    result = await collect(BoomStream())
    assert names(result) == ["ready", "error"]
    assert payloads(result, "error")[0]["message"] == "upstream boom"


async def test_stream_error_can_raise_for_non_stream_endpoint():
    with pytest.raises(RuntimeError):
        await collect(BoomStream(), on_error="raise")


# ---------------------------------------------------------------------------
# 12) 端点级联调（TestClient + SQLite + fake stream）：SSE 落库规则
# ---------------------------------------------------------------------------


@pytest.fixture()
def chat_client(client_factory, sqlite_session, monkeypatch):
    """挂载 legacy_chat.router 的测试 app；落库用同一个 SQLite session。"""
    import contextlib

    from app.api import chat as chat_service
    from app.api import legacy_chat
    from app.core.timeutil import now, truncate_to_second
    from app.db.models import ChatConversation

    stamp = truncate_to_second(now())
    conversation = ChatConversation(user_id=1, title="", created_at=stamp, updated_at=stamp, favorite=False)
    sqlite_session.add(conversation)
    sqlite_session.commit()
    sqlite_session.refresh(conversation)

    monkeypatch.setattr(chat_service, "SessionLocal", lambda: contextlib.nullcontext(sqlite_session))

    # 让记忆链路完全离线：向量写入/召回都降级，避免测试依赖本机 Ollama/PG
    from app.memory import long as long_memory

    async def _no_embed_async(text: str):  # noqa: ARG001
        return None

    monkeypatch.setattr(long_memory, "embed_sync", lambda text: None)
    monkeypatch.setattr(long_memory, "embed_async", _no_embed_async)
    monkeypatch.setattr(long_memory, "store_message_vector", lambda *args, **kwargs: False)
    monkeypatch.setattr(long_memory, "recall_semantic", lambda *args, **kwargs: [])

    client = client_factory(legacy_chat.router, sqlite_session)
    return client, conversation, sqlite_session


def _frames(raw: str) -> list[tuple[str, dict[str, Any]]]:
    parsed: list[tuple[str, dict[str, Any]]] = []
    for frame in raw.split("\n\n"):
        if not frame.strip():
            continue
        lines = frame.split("\n")
        name = next(line[len("event:") :].strip() for line in lines if line.startswith("event:"))
        data = json.loads(next(line[len("data:") :].strip() for line in lines if line.startswith("data:")))
        parsed.append((name, data))
    return parsed


def test_sse_endpoint_streams_events_and_persists_only_final_answer(chat_client, monkeypatch):
    from app.agent import llm
    from app.db.models import ChatMessage

    client, conversation, sqlite_session = chat_client
    monkeypatch.setattr(
        llm,
        "open_stream",
        ScriptedStream(
            [
                [text_chunk("我先查一下。"), tool_chunk(0, "call_1", "getCurrentTime", "{}"), finish_chunk("tool_calls")],
                [text_chunk("现在是下午三点。"), finish_chunk("stop")],
            ]
        ),
    )

    with client.stream(
        "GET",
        f"/test/chat/stream/events?model=1&userInput=现在几点&conversationId={conversation.id}",
    ) as response:
        assert response.status_code == 200
        assert response.headers["content-type"].startswith("text/event-stream")
        assert response.headers["x-accel-buffering"] == "no"
        frames = _frames("".join(response.iter_text()))

    event_names = [name for name, _ in frames]
    assert event_names[0] == "ready"
    assert event_names[-1] == "done"
    assert event_names.count("tool_call") == 2
    assert frames[0][1] == {"conversation_id": conversation.id}
    assert any(name == "segment_boundary" and data == {"reason": "final_answer"} for name, data in frames)

    from sqlalchemy import select

    rows = [
        (row.role, row.content)
        for row in sqlite_session.execute(
            select(ChatMessage).where(ChatMessage.conversation_id == conversation.id).order_by(ChatMessage.id)
        )
        .scalars()
        .all()
    ]
    assert rows == [("user", "现在几点"), ("assistant", "现在是下午三点。")]


def test_plain_stream_endpoint_does_not_duplicate_final_answer(chat_client, monkeypatch):
    from app.agent import llm

    client, conversation, _session = chat_client
    monkeypatch.setattr(
        llm,
        "open_stream",
        ScriptedStream(
            [
                [text_chunk("我先查一下。"), tool_chunk(0, "call_p", "getCurrentTime", "{}"), finish_chunk("tool_calls")],
                [text_chunk("现在是下午三点。"), finish_chunk("stop")],
            ]
        ),
    )
    response = client.get(f"/test/chat/stream?model=1&userInput=纯文本&conversationId={conversation.id}")
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/plain")
    assert response.text == "我先查一下。现在是下午三点。"


def test_non_stream_endpoint_returns_plain_text_and_400_for_bad_model(chat_client, monkeypatch):
    from app.agent import llm

    client, conversation, _session = chat_client
    monkeypatch.setattr(llm, "open_stream", ScriptedStream([[text_chunk("直接回答"), finish_chunk("stop")]]))
    response = client.get(f"/test/chat?model=1&userInput=hi&conversationId={conversation.id}")
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/plain")
    assert response.text == "直接回答"

    bad = client.get("/test/chat?model=9&userInput=hi")
    assert bad.status_code == 400
    assert bad.json()["message"] == "model must be 1 or 2"
    missing = client.get(f"/test/chat?model=1&userInput=hi&conversationId={conversation.id + 999}")
    assert missing.status_code == 404
    assert missing.json()["message"] == "会话不存在"
