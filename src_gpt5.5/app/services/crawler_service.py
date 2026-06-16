from __future__ import annotations

import html
import re
import time
import urllib.error
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Callable

from app.config import Settings


STATUS_URL_RE = re.compile(r"https://truthsocial\.com/@realDonaldTrump/(\d+)")
MEDIA_RE = re.compile(r"https?://[^\s\"')>]+(?:jpg|jpeg|png|gif|webp|mp4|mov|webm)", re.I)
CrawlLog = Callable[[str, str], None]


@dataclass
class CrawledStatus:
    source_status_id: int
    source_url: str
    title: str
    author: str
    published_at: str
    original_url: str | None
    status_id: str | None
    content: str
    attachments: list[str]


def crawl_new_statuses(
    settings: Settings,
    start_after: int | None = None,
    batch_size: int | None = None,
    download_attachments_enabled: bool | None = None,
    log: CrawlLog | None = None,
) -> dict[str, Any]:
    progress_path = settings.paths.content_root / settings.crawler.progress_file
    current = start_after if start_after is not None else read_progress(progress_path)
    batch = batch_size or settings.crawler.batch_size
    request_delay = max(0.0, float(getattr(settings.crawler, "request_delay_seconds", 0.1) or 0))
    max_workers = max(1, int(getattr(settings.crawler, "max_workers", 4) or 1))
    should_download = (
        settings.crawler.download_attachments
        if download_attachments_enabled is None
        else download_attachments_enabled
    )
    max_success = current
    checked = 0
    saved = 0
    missing = 0
    failed = 0
    errors: list[dict[str, str]] = []
    files: list[str] = []
    started = time.perf_counter()
    range_start = current + 1
    range_end = current + batch
    source_ids = list(range(range_start, range_end + 1))

    _log(
        log,
        "INFO",
        (
            f"抓取范围 {range_start}-{range_end}；批量 {batch}；"
            f"超时 {settings.crawler.request_timeout_seconds}s；请求间隔 {request_delay}s；"
            f"并发请求 {max_workers}；"
            f"附件下载={'开启' if should_download else '关闭'}"
        ),
    )

    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        futures = {}
        for source_id in source_ids:
            url = f"{settings.crawler.base_url}/{source_id}"
            _log(log, "INFO", f"提交检查 status {source_id}: {url}")
            futures[executor.submit(_fetch_status_html, source_id, url, settings.crawler.request_timeout_seconds)] = url

        for future in as_completed(futures):
            result = future.result()
            checked += 1
            source_id = int(result["source_id"])
            url = str(result["url"])
            fetch_seconds = float(result["seconds"])
            if result["error_type"] == "http":
                status_code = int(result["status_code"])
                if status_code == 404:
                    missing += 1
                    _log(log, "INFO", f"[{checked}/{batch}] HTTP 404 status {source_id}，请求耗时 {fetch_seconds}s")
                else:
                    failed += 1
                    errors.append({"url": url, "error": f"HTTP {status_code}"})
                    _log(log, "ERROR", f"[{checked}/{batch}] 抓取失败 {url}：HTTP {status_code}，请求耗时 {fetch_seconds}s")
            elif result["error_type"] == "exception":
                failed += 1
                errors.append({"url": url, "error": str(result["error"])})
                _log(log, "ERROR", f"[{checked}/{batch}] 抓取失败 {url}：{result['error']}，请求耗时 {fetch_seconds}s")
            else:
                html_text = str(result["html_text"])
                if is_not_found(html_text):
                    missing += 1
                    _log(log, "INFO", f"[{checked}/{batch}] 未找到 status {source_id}，请求耗时 {fetch_seconds}s")
                else:
                    item_started = time.perf_counter()
                    try:
                        status = parse_status_html(source_id, url, html_text)
                        markdown_path = save_status_markdown(settings, status)
                        attachment_result = {"attempted": 0, "saved": 0, "failed": 0, "seconds": 0.0}
                        if should_download:
                            attachment_result = download_attachments(settings, status, markdown_path, log=log)
                        files.append(str(markdown_path))
                        saved += 1
                        max_success = max(max_success, source_id)
                        _log(
                            log,
                            "INFO",
                            (
                                f"[{checked}/{batch}] 已保存 status {source_id} -> {markdown_path}；"
                                f"页面请求 {fetch_seconds}s，处理 {_elapsed(item_started)}s；"
                                f"远程附件 {len(status.attachments)} 个，下载成功 {attachment_result['saved']} 个，"
                                f"失败 {attachment_result['failed']} 个"
                            ),
                        )
                        if request_delay:
                            time.sleep(request_delay)
                    except Exception as exc:  # noqa: BLE001
                        failed += 1
                        errors.append({"url": url, "error": str(exc)})
                        _log(log, "ERROR", f"[{checked}/{batch}] 保存或解析失败 {url}：{exc}")

            if checked % 10 == 0 or checked == batch:
                _log(
                    log,
                    "INFO",
                    (
                        f"进度汇总：已完成 {checked}/{batch}，保存 {saved}，"
                        f"未找到 {missing}，失败 {failed}，当前最大成功编号 {max_success}"
                    ),
                )

    if max_success > current:
        progress_path.write_text(str(max_success), encoding="utf-8")
        _log(log, "INFO", f"已更新进度文件 {progress_path} -> {max_success}")
    else:
        _log(log, "INFO", f"没有新的成功编号，进度文件保持 {current}")

    total_seconds = round(time.perf_counter() - started, 3)
    _log(
        log,
        "INFO",
        (
            f"抓取完成：检查 {checked}，保存 {saved}，未找到 {missing}，失败 {failed}，"
            f"总耗时 {total_seconds}s，平均每条 {round(total_seconds / checked, 3) if checked else 0}s"
        ),
    )

    return {
        "checked": checked,
        "saved": saved,
        "missing": missing,
        "failed": failed,
        "max_success": max_success,
        "seconds": total_seconds,
        "avg_seconds_per_checked": round(total_seconds / checked, 3) if checked else 0,
        "request_delay_seconds": request_delay,
        "max_workers": max_workers,
        "download_attachments": should_download,
        "files": files,
        "errors": errors[:50],
    }


def read_progress(path: Path) -> int:
    if not path.exists():
        return 0
    text = path.read_text(encoding="utf-8", errors="replace").strip()
    match = re.search(r"\d+", text)
    return int(match.group(0)) if match else 0


def fetch_url(url: str, timeout: int) -> str:
    request = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return response.read().decode("utf-8", errors="replace")


def _fetch_status_html(source_id: int, url: str, timeout: int) -> dict[str, Any]:
    started = time.perf_counter()
    try:
        return {
            "source_id": source_id,
            "url": url,
            "html_text": fetch_url(url, timeout),
            "error_type": None,
            "status_code": None,
            "error": None,
            "seconds": _elapsed(started),
        }
    except urllib.error.HTTPError as exc:
        return {
            "source_id": source_id,
            "url": url,
            "html_text": "",
            "error_type": "http",
            "status_code": exc.code,
            "error": f"HTTP {exc.code}",
            "seconds": _elapsed(started),
        }
    except Exception as exc:  # noqa: BLE001
        return {
            "source_id": source_id,
            "url": url,
            "html_text": "",
            "error_type": "exception",
            "status_code": None,
            "error": str(exc),
            "seconds": _elapsed(started),
        }


def is_not_found(html_text: str) -> bool:
    text = html_text.lower()
    return "404" in text and ("not found" in text or "page not found" in text)


def parse_status_html(source_id: int, source_url: str, html_text: str) -> CrawledStatus:
    title = _first_match(html_text, r"<title[^>]*>(.*?)</title>") or f"Status {source_id}"
    title = clean_text(title)

    original_url = None
    status_id = None
    status_match = STATUS_URL_RE.search(html_text)
    if status_match:
        status_id = status_match.group(1)
        original_url = status_match.group(0)

    published = (
        _first_match(html_text, r"发布时间</[^>]+>\s*([^<]+)")
        or _first_match(html_text, r"Published[^<]*</[^>]+>\s*([^<]+)")
        or _first_match(html_text, r"([A-Za-z]+,\s+[A-Za-z]+\s+\d{1,2},\s+\d{4},\s+\d{1,2}:\d{2}\s+[AP]M\s+E[DS]T)")
        or ""
    )
    content = _extract_content(html_text)
    if not title or title.lower().startswith("status"):
        title = _title_from_content(content, source_id)
    attachments = sorted(set(MEDIA_RE.findall(html_text)))
    return CrawledStatus(
        source_status_id=source_id,
        source_url=source_url,
        title=title,
        author="Donald J. Trump (@realDonaldTrump)",
        published_at=clean_text(published),
        original_url=original_url,
        status_id=status_id,
        content=content,
        attachments=attachments,
    )


def save_status_markdown(settings: Settings, status: CrawledStatus) -> Path:
    dt = _date_from_published(status.published_at)
    year = dt.strftime("%Y") if dt else datetime.now().strftime("%Y")
    month = dt.strftime("%m") if dt else datetime.now().strftime("%m")
    prefix_date = dt.strftime("%Y-%m-%d") if dt else datetime.now().strftime("%Y-%m-%d")
    target_dir = settings.paths.content_root / year / month
    target_dir.mkdir(parents=True, exist_ok=True)
    filename = f"{prefix_date} {safe_filename(status.title)}.md"
    path = unique_path(target_dir / filename)
    attachments_text = "\n".join(f"- {url}" for url in status.attachments) if status.attachments else "无"
    markdown = (
        f"# {status.title}\n\n"
        f"- **作者**: {status.author}\n"
        f"- **发布时间**: {status.published_at}\n"
        f"- **原始链接**: {status.original_url or ''}\n"
        f"- **TRUTH Social status ID**: `{status.status_id or ''}`\n"
        f"- **来源**: {status.source_url}\n\n"
        "---\n\n"
        "## 内容\n\n"
        f"{status.content}\n\n"
        "---\n\n"
        "## 附件\n\n"
        f"{attachments_text}\n"
    )
    path.write_text(markdown, encoding="utf-8")
    return path


def download_attachments(
    settings: Settings,
    status: CrawledStatus,
    markdown_path: Path,
    log: CrawlLog | None = None,
) -> dict[str, Any]:
    started = time.perf_counter()
    result = {"attempted": 0, "saved": 0, "failed": 0, "seconds": 0.0}
    if not status.attachments:
        return result
    target_dir = markdown_path.parent / "attachments" / str(status.source_status_id)
    target_dir.mkdir(parents=True, exist_ok=True)
    for index, url in enumerate(status.attachments, start=1):
        result["attempted"] += 1
        try:
            parsed = urllib.parse.urlparse(url)
            suffix = Path(parsed.path).suffix or ".bin"
            local = target_dir / f"{index:02d}{suffix}"
            request = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
            with urllib.request.urlopen(request, timeout=settings.crawler.request_timeout_seconds) as response:
                local.write_bytes(response.read())
            result["saved"] += 1
        except Exception:
            result["failed"] += 1
            _log(log, "WARN", f"附件下载失败 status {status.source_status_id} #{index}: {url}")
            continue
    result["seconds"] = round(time.perf_counter() - started, 3)
    if result["attempted"]:
        _log(
            log,
            "INFO",
            (
                f"附件下载完成 status {status.source_status_id}：尝试 {result['attempted']}，"
                f"成功 {result['saved']}，失败 {result['failed']}，耗时 {result['seconds']}s"
            ),
        )
    return result


def _log(callback: CrawlLog | None, level: str, message: str) -> None:
    if callback:
        callback(level, message)


def _elapsed(started: float) -> float:
    return round(time.perf_counter() - started, 3)


def unique_path(path: Path) -> Path:
    if not path.exists():
        return path
    stem, suffix = path.stem, path.suffix
    for i in range(2, 1000):
        candidate = path.with_name(f"{stem} ({i}){suffix}")
        if not candidate.exists():
            return candidate
    return path


def safe_filename(value: str) -> str:
    replacements = {
        "@": " at ",
        "#": " tag ",
        "&": " and ",
        "%": " percent ",
        "+": " plus ",
        "=": " equals ",
        "$": " dollar ",
        "€": " euro ",
        "£": " pound ",
        "¥": " yen ",
        "—": "-",
        "–": "-",
        "…": "...",
        "’": "",
        "'": "",
        '"': "",
    }
    for src, dst in replacements.items():
        value = value.replace(src, dst)
    value = re.sub(r"https?://", " link ", value, flags=re.I)
    value = value.encode("ascii", errors="ignore").decode("ascii")
    value = re.sub(r"[^A-Za-z0-9._ -]+", "_", value)
    value = re.sub(r"\s+", " ", value)
    value = re.sub(r"_+", "_", value)
    value = value.strip(" ._-")
    return value[:120] or "Status"


def clean_text(value: str) -> str:
    value = html.unescape(value or "")
    value = re.sub(r"<[^>]+>", " ", value)
    value = re.sub(r"\s+", " ", value)
    return value.strip()


def _extract_content(html_text: str) -> str:
    candidates = [
        r'<div[^>]+class="[^"]*status__content[^"]*"[^>]*>(.*?)</div>',
        r'<div[^>]+class="[^"]*status[^"]*"[^>]*>(.*?)</div>',
        r'<article[^>]*>(.*?)</article>',
        r'<meta[^>]+property="og:description"[^>]+content="([^"]+)"',
        r'<meta[^>]+name="description"[^>]+content="([^"]+)"',
    ]
    for pattern in candidates:
        match = re.search(pattern, html_text, re.I | re.S)
        if match:
            text = clean_text(match.group(1))
            if len(text) > 20:
                return text
    return ""


def _title_from_content(content: str, source_id: int) -> str:
    words = re.sub(r"\s+", " ", content).strip().split()
    if not words:
        return f"Status {source_id}"
    return " ".join(words[:8])


def _first_match(text: str, pattern: str) -> str | None:
    match = re.search(pattern, text, re.I | re.S)
    return match.group(1) if match else None


def _date_from_published(value: str) -> datetime | None:
    if not value:
        return None
    cleaned = re.sub(r"^[A-Za-z]+,\s*", "", value)
    cleaned = re.sub(r"\s+E[DS]T\s*$", "", cleaned)
    for fmt in ("%B %d, %Y, %I:%M %p", "%b %d, %Y, %I:%M %p"):
        try:
            return datetime.strptime(cleaned, fmt)
        except ValueError:
            continue
    return None
