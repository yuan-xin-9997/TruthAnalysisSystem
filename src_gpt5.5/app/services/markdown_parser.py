from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone, timedelta
from pathlib import Path


META_RE = re.compile(r"^-\s*\*\*(?P<key>[^*]+)\*\*:\s*(?P<value>.*)$", re.MULTILINE)
URL_RE = re.compile(r"https?://[^\s)>\]]+")


@dataclass
class Attachment:
    attachment_type: str
    url: str | None = None
    local_path: str | None = None
    description: str | None = None
    raw_text: str | None = None


@dataclass
class ParsedPost:
    title: str | None = None
    author_name: str | None = None
    author_handle: str | None = None
    published_at_raw: str | None = None
    published_at_utc: str | None = None
    published_at_et: str | None = None
    published_date: str | None = None
    original_url: str | None = None
    status_id: str | None = None
    source_url: str | None = None
    source_status_id: int | None = None
    content_raw: str | None = None
    content_clean: str | None = None
    attachments: list[Attachment] = field(default_factory=list)
    file_path: str | None = None
    file_hash: str | None = None
    parse_status: str = "success"
    warnings: list[str] = field(default_factory=list)


def file_hash(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def looks_like_post(text: str) -> bool:
    markers = ["## 内容", "TRUTH Social status ID", "**发布时间**", "truthsocial.com"]
    return any(marker in text for marker in markers)


def parse_markdown(path: Path, text: str | None = None) -> ParsedPost:
    raw = text if text is not None else path.read_text(encoding="utf-8", errors="replace")
    post = ParsedPost(file_path=_safe_text(str(path)), file_hash=file_hash(path))
    title_match = re.search(r"^\s*#\s+(.+?)\s*$", raw, re.MULTILINE)
    post.title = title_match.group(1).strip() if title_match else path.stem

    meta = {m.group("key").strip(): _clean_meta(m.group("value")) for m in META_RE.finditer(raw)}
    _parse_author(post, meta.get("作者"))
    post.published_at_raw = meta.get("发布时间")
    post.original_url = meta.get("原始链接")
    post.status_id = meta.get("TRUTH Social status ID")
    post.source_url = meta.get("来源")
    post.source_status_id = _extract_source_status_id(post.source_url)

    if post.status_id:
        post.status_id = re.sub(r"\D", "", post.status_id) or None
    if not post.status_id and post.original_url:
        status_match = re.search(r"/(\d{8,})/?$", post.original_url)
        if status_match:
            post.status_id = status_match.group(1)

    post.content_raw = _extract_section(raw, "内容")
    post.content_clean = clean_content(post.content_raw or "")
    post.attachments = _parse_attachments(_extract_section(raw, "附件"))

    _parse_time(post)
    if not post.published_date:
        file_date = re.search(r"(20\d{2}-\d{2}-\d{2})", path.name)
        if file_date:
            post.published_date = file_date.group(1)

    if not post.content_clean:
        post.parse_status = "partial"
        post.warnings.append("content_missing")
    if not post.published_at_raw:
        post.parse_status = "partial"
        post.warnings.append("published_at_missing")
    return post


def clean_content(text: str) -> str:
    text = re.sub(r"^\s*---+\s*$", " ", text, flags=re.MULTILINE)
    text = re.sub(r"\s+", " ", text)
    return text.strip()


def _safe_text(value: str) -> str:
    return value.encode("utf-8", errors="replace").decode("utf-8")


def _clean_meta(value: str) -> str:
    value = value.strip()
    value = value.strip("`")
    return value.strip()


def _parse_author(post: ParsedPost, value: str | None) -> None:
    if not value:
        post.author_name = "Donald J. Trump"
        post.author_handle = "@realDonaldTrump"
        return
    handle = re.search(r"\((@[^)]+)\)", value)
    post.author_handle = handle.group(1) if handle else None
    post.author_name = re.sub(r"\s*\(@[^)]+\)\s*", "", value).strip() or value


def _extract_section(raw: str, heading: str) -> str:
    pattern = re.compile(
        rf"^##\s+{re.escape(heading)}\s*$\s*(?P<body>.*?)(?=^\s*---+\s*$\s*^##\s+|^##\s+|\Z)",
        re.MULTILINE | re.DOTALL,
    )
    match = pattern.search(raw)
    return match.group("body").strip() if match else ""


def _parse_attachments(raw: str) -> list[Attachment]:
    text = (raw or "").strip()
    if not text:
        return []
    normalized = text.lower()
    if normalized in {"无", "none", "no attachments", "*(no attachments)*"}:
        return []
    if "no attachments" in normalized and len(normalized) < 80:
        return []
    urls = URL_RE.findall(text)
    attachments: list[Attachment] = []
    for url in urls:
        lower = url.lower()
        if any(lower.endswith(ext) for ext in [".jpg", ".jpeg", ".png", ".gif", ".webp"]):
            kind = "image"
        elif any(lower.endswith(ext) for ext in [".mp4", ".mov", ".webm", ".m3u8"]):
            kind = "video"
        else:
            kind = "link"
        attachments.append(Attachment(attachment_type=kind, url=url, raw_text=text))
    if not attachments:
        attachments.append(Attachment(attachment_type="unknown", raw_text=text))
    return attachments


def _extract_source_status_id(source_url: str | None) -> int | None:
    if not source_url:
        return None
    match = re.search(r"/statuses/(\d+)", source_url)
    return int(match.group(1)) if match else None


def _parse_time(post: ParsedPost) -> None:
    if not post.published_at_raw:
        return
    raw = post.published_at_raw.strip()
    tz_match = re.search(r"\b(EDT|EST)\b", raw)
    offset = timedelta(hours=-4 if tz_match and tz_match.group(1) == "EDT" else -5)
    without_tz = re.sub(r"\s+(EDT|EST)\s*$", "", raw)
    without_weekday = re.sub(r"^[A-Za-z]+,\s*", "", without_tz)
    for fmt in ("%B %d, %Y, %I:%M %p", "%b %d, %Y, %I:%M %p"):
        try:
            naive = datetime.strptime(without_weekday, fmt)
            et = naive.replace(tzinfo=timezone(offset))
            post.published_at_et = et.isoformat()
            post.published_at_utc = et.astimezone(timezone.utc).isoformat()
            post.published_date = et.date().isoformat()
            return
        except ValueError:
            continue
    post.warnings.append("published_at_unparsed")
