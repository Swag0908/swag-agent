"""书签图标发现与缓存，对齐 Java `WebsiteIconService`。

- 首次读取 `/bookmarks/{id}/icon` 时抓取站点图标，之后只返回数据库缓存；
- SSRF 防护：只允许 http/https，且解析后的所有地址都必须公网；
- 上限：页面 256 KiB、图标 512 KiB；不跟随重定向；超时 3s/5s；
- 网络失败/无图标返回 None，不影响书签本身。
"""

from __future__ import annotations

import ipaddress
import re
import socket
from urllib.parse import urljoin, urlsplit

import httpx
from sqlalchemy.orm import Session

from app.core import timeutil
from app.core.errors import NotFound
from app.db.models import WebsiteBookmark
from app.domains.sites import repository

MAX_ICON_BYTES = 512 * 1024
MAX_PAGE_BYTES = 256 * 1024
USER_AGENT = "SwagAgent-BookmarkIcon/1.0"

LINK_TAG = re.compile(r"<link\b[^>]*>", re.IGNORECASE)
REL = re.compile(r"\brel\s*=\s*(['\"])(.*?)\1", re.IGNORECASE)
HREF = re.compile(r"\bhref\s*=\s*(['\"])(.*?)\1", re.IGNORECASE)


def icon_for(db: Session, user_id: int, bookmark_id: int) -> tuple[bytes, str] | None:
    """返回 `(bytes, content_type)`；无缓存时尝试发现并落库。"""
    bookmark = _owned_bookmark(db, user_id, bookmark_id)
    cached = repository.find_cached_icon(db, bookmark_id, user_id)
    if cached is not None:
        return cached
    discovered = discover(bookmark)
    if discovered is not None:
        repository.store_cached_icon(db, bookmark, discovered[0], discovered[1])
        bookmark.updated_at = timeutil.now()
        db.commit()
    return discovered


def discover(bookmark: WebsiteBookmark) -> tuple[bytes, str] | None:
    """按 Java 的候选顺序找图标：iconUrl → 页面声明的 icon → /favicon.ico/png → apple-touch-icon。"""
    try:
        site = bookmark.url
        urlsplit(site)
    except ValueError:
        return None

    candidates: list[str] = []
    if bookmark.icon_url is not None and bookmark.icon_url.strip():
        candidates.append(urljoin(site, bookmark.icon_url.strip()))
    candidates.extend(_icons_declared_by(site))
    for path in ("/favicon.ico", "/favicon.png", "/apple-touch-icon.png"):
        candidates.append(urljoin(site, path))

    for candidate in dict.fromkeys(candidates):
        found = _download_image(candidate)
        if found is not None:
            return found
    return None


def _icons_declared_by(site: str) -> list[str]:
    page = _request(site, MAX_PAGE_BYTES, "text/html,application/xhtml+xml")
    if page is None:
        return []
    data, content_type = page
    if "html" not in content_type.lower():
        return []
    html = data.decode("utf-8", errors="replace")
    result: list[str] = []
    for tag in LINK_TAG.findall(html):
        rel = REL.search(tag)
        href = HREF.search(tag)
        if not rel or not href or "icon" not in rel.group(2).lower():
            continue
        try:
            result.append(urljoin(site, href.group(2).strip()))
        except ValueError:
            continue
    return result


def _download_image(url: str) -> tuple[bytes, str] | None:
    response = _request(
        url,
        MAX_ICON_BYTES,
        "image/avif,image/webp,image/apng,image/svg+xml,image/*,*/*;q=0.8",
    )
    if response is None:
        return None
    data, content_type = response
    if not content_type.lower().startswith("image/") or not data:
        return None
    return data, content_type


def _request(url: str, max_bytes: int, accept: str) -> tuple[bytes, str] | None:
    """GET 一个公网 URL，最多读取 max_bytes；任何网络错误都返回 None。"""
    if not is_public_http_uri(url):
        return None
    try:
        with httpx.Client(
            timeout=httpx.Timeout(5.0, connect=3.0),
            follow_redirects=False,
            headers={"User-Agent": USER_AGENT, "Accept": accept},
        ) as client:
            with client.stream("GET", url) as response:
                if response.status_code < 200 or response.status_code >= 300:
                    return None
                buffer = bytearray()
                for chunk in response.iter_bytes():
                    buffer.extend(chunk)
                    if len(buffer) > max_bytes:
                        return None
                content_type = response.headers.get("content-type", "application/octet-stream")
                content_type = content_type.split(";", 2)[0].strip() or "application/octet-stream"
                return bytes(buffer), content_type
    except (httpx.HTTPError, OSError, ValueError):
        return None


def is_public_http_uri(url: str) -> bool:
    try:
        parts = urlsplit(url)
    except ValueError:
        return False
    if parts.scheme not in {"http", "https"} or not parts.hostname:
        return False
    try:
        infos = socket.getaddrinfo(parts.hostname, None)
    except OSError:
        return False
    if not infos:
        return False
    for info in infos:
        raw_ip = str(info[4][0]).split("%", 1)[0]
        try:
            address = ipaddress.ip_address(raw_ip)
        except ValueError:
            return False
        if _is_private_address(address):
            return False
    return True


def _is_private_address(address: ipaddress.IPv4Address | ipaddress.IPv6Address) -> bool:
    return (
        address.is_private
        or address.is_loopback
        or address.is_link_local
        or address.is_multicast
        or address.is_unspecified
        or address.is_reserved
    )


def _owned_bookmark(db: Session, user_id: int, bookmark_id: int) -> WebsiteBookmark:
    bookmark = repository.find_bookmark(db, bookmark_id)
    if bookmark is None or bookmark.user_id != user_id:
        raise NotFound(f"网站不存在：#{bookmark_id}")
    return bookmark


__all__ = ["icon_for", "discover", "is_public_http_uri", "MAX_ICON_BYTES", "MAX_PAGE_BYTES"]
