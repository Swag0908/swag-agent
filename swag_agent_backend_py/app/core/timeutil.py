"""时间与日期工具：与 Java 端 LocalDateTime/LocalDate/Instant/epoch ms 的序列化对齐。

Java 端运行在 Asia/Shanghai；MySQL DATETIME 无时区。约定：
- 业务层统一使用 naive 的 Asia/Shanghai datetime（等价于 Java LocalDateTime.now()）。
- 对外的 epoch 毫秒按 Asia/Shanghai 解释。
"""

from __future__ import annotations

from datetime import date, datetime, time, timedelta
from zoneinfo import ZoneInfo

TZ = ZoneInfo("Asia/Shanghai")


def now() -> datetime:
    """Java LocalDateTime.now() 等价：naive 的东八区当前时间。"""
    return datetime.now(TZ).replace(tzinfo=None)


def now_utc() -> datetime:
    return datetime.now(tz=ZoneInfo("UTC"))


def today() -> date:
    return now().date()


def epoch_ms(value: datetime | date | None) -> int:
    """Java null 时间字段在会话/记忆接口输出 0。"""
    if value is None:
        return 0
    if isinstance(value, date) and not isinstance(value, datetime):
        value = datetime.combine(value, time.min)
    if value.tzinfo is None:
        value = value.replace(tzinfo=TZ)
    return int(value.timestamp() * 1000)


def epoch_ms_or_none(value: datetime | None) -> int | None:
    if value is None:
        return None
    return epoch_ms(value)


def from_epoch_ms(ms: int | None) -> datetime | None:
    if ms is None:
        return None
    return datetime.fromtimestamp(ms / 1000, TZ).replace(tzinfo=None)


def iso_instant(value: datetime | None) -> str | None:
    """Java Instant 的 JSON 形态：UTC，Z 结尾。"""
    if value is None:
        return None
    if value.tzinfo is None:
        value = value.replace(tzinfo=TZ)
    return value.astimezone(ZoneInfo("UTC")).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def local_datetime_json(value: datetime | None) -> str | None:
    """Java LocalDateTime 的 JSON 形态：无时区、无微秒（有则保留）。"""
    if value is None:
        return None
    if value.microsecond:
        return value.isoformat(timespec="milliseconds")
    return value.isoformat(timespec="seconds")


def local_date_str(value: date | None) -> str | None:
    return value.isoformat() if value else None


def local_time_str(value: time | None) -> str | None:
    if value is None:
        return None
    return value.replace(microsecond=0).isoformat(timespec="seconds")


def truncate_to_second(value: datetime | None) -> datetime | None:
    """DATETIME(0) 表（chat_* / chat_user_memory*）写入前置零。"""
    if value is None:
        return None
    return value.replace(microsecond=0)


def truncate_to_microsecond(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    return value.replace(microsecond=value.microsecond)


_CN_DATE_WORDS = {
    "today": 0,
    "今天": 0,
    "tomorrow": 1,
    "明天": 1,
}


def parse_due_date(raw: str | None, fallback: date | None = None) -> date | None:
    """待办日期宽容解析：today/今天/tomorrow/明天/yyyy-MM-dd。

    与 Java 行为一致：非法输入返回 fallback（创建时回退今天，更新/延期时为 None）。
    """
    if raw is None:
        return fallback
    text = raw.strip()
    if not text:
        return fallback
    lowered = text.lower()
    if lowered in _CN_DATE_WORDS:
        return today() + timedelta(days=_CN_DATE_WORDS[lowered])
    try:
        return date.fromisoformat(text)
    except ValueError:
        return fallback


def parse_due_time(raw: str | None) -> time | None:
    """HH:mm 或 HH:mm:ss；非法静默为 None。"""
    if raw is None:
        return None
    text = raw.strip()
    if not text:
        return None
    for fmt in ("%H:%M", "%H:%M:%S"):
        try:
            return datetime.strptime(text, fmt).time()
        except ValueError:
            continue
    return None


def title_from_text(text: str | None, limit: int = 40) -> str:
    """会话标题：压缩空白后取前 40 字，超长加 …。"""
    flat = " ".join((text or "").split())
    return flat if len(flat) <= limit else flat[:limit] + "…"
