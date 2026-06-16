from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Any

from app.db import refresh_post_fts
from app.services.markdown_parser import ParsedPost, looks_like_post, parse_markdown


EXCLUDED_NAMES = {
    "已抓取.md",
    "需求.md",
    "特朗普真实社交贴文分析系统需求.md",
    "特朗普真实社交贴文分析系统需求规格说明书.md",
    "特朗普真实社交贴文分析系统设计说明书.md",
}


def scan_markdown_files(content_root: Path, source_root: Path) -> list[Path]:
    files: list[Path] = []
    for path in content_root.rglob("*.md"):
        if path.name in EXCLUDED_NAMES:
            continue
        try:
            path.relative_to(source_root)
            continue
        except ValueError:
            pass
        files.append(path)
    return files


def import_markdown_tree(
    conn: sqlite3.Connection,
    content_root: Path,
    source_root: Path,
    limit: int | None = None,
    commit_every: int = 250,
) -> dict[str, Any]:
    scanned = 0
    candidates = 0
    inserted = 0
    updated = 0
    skipped = 0
    failed = 0
    errors: list[dict[str, str]] = []

    processed_candidates = 0
    for path in scan_markdown_files(content_root, source_root):
        scanned += 1
        if limit is not None and processed_candidates >= limit:
            break
        try:
            text = path.read_text(encoding="utf-8", errors="replace")
            if not looks_like_post(text):
                skipped += 1
                continue
            candidates += 1
            processed_candidates += 1
            parsed = parse_markdown(path, text)
            result = upsert_post(conn, parsed)
            if result == "inserted":
                inserted += 1
            elif result == "updated":
                updated += 1
            else:
                skipped += 1
        except Exception as exc:  # noqa: BLE001
            failed += 1
            errors.append({"file": str(path), "error": str(exc)})
        if candidates and candidates % commit_every == 0:
            conn.commit()
    conn.commit()
    return {
        "scanned": scanned,
        "candidates": candidates,
        "inserted": inserted,
        "updated": updated,
        "skipped": skipped,
        "failed": failed,
        "errors": errors[:50],
    }


def upsert_post(conn: sqlite3.Connection, parsed: ParsedPost) -> str:
    existing = _find_existing(conn, parsed)
    values = {
        "status_id": parsed.status_id,
        "source_status_id": parsed.source_status_id,
        "title": parsed.title,
        "author_name": parsed.author_name,
        "author_handle": parsed.author_handle,
        "published_at_raw": parsed.published_at_raw,
        "published_at_utc": parsed.published_at_utc,
        "published_at_et": parsed.published_at_et,
        "published_date": parsed.published_date,
        "original_url": parsed.original_url,
        "source_url": parsed.source_url,
        "content_raw": parsed.content_raw,
        "content_clean": parsed.content_clean,
        "is_retruth": 1 if _is_retruth(parsed) else 0,
        "has_attachment": 1 if parsed.attachments else 0,
        "word_count": len((parsed.content_clean or "").split()),
        "char_count": len(parsed.content_clean or ""),
        "file_path": parsed.file_path,
        "file_hash": parsed.file_hash,
        "parse_status": parsed.parse_status,
    }
    if existing:
        if existing["file_hash"] == parsed.file_hash:
            if existing["file_path"] != parsed.file_path:
                conn.execute(
                    "UPDATE posts SET file_path = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?",
                    (parsed.file_path, existing["id"]),
                )
                return "updated"
            return "skipped"
        sets = ", ".join(f"{key} = ?" for key in values)
        conn.execute(
            f"UPDATE posts SET {sets}, updated_at = CURRENT_TIMESTAMP WHERE id = ?",
            (*values.values(), existing["id"]),
        )
        post_id = int(existing["id"])
        conn.execute("DELETE FROM post_attachments WHERE post_id = ?", (post_id,))
        action = "updated"
    else:
        cols = ", ".join(values.keys())
        placeholders = ", ".join("?" for _ in values)
        cur = conn.execute(
            f"INSERT INTO posts ({cols}) VALUES ({placeholders})", tuple(values.values())
        )
        post_id = int(cur.lastrowid)
        action = "inserted"

    for item in parsed.attachments:
        conn.execute(
            """
            INSERT INTO post_attachments
              (post_id, attachment_type, url, local_path, description, raw_text)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                post_id,
                item.attachment_type,
                item.url,
                item.local_path,
                item.description,
                item.raw_text,
            ),
        )
    refresh_post_fts(conn, post_id)
    return action


def _find_existing(conn: sqlite3.Connection, parsed: ParsedPost) -> sqlite3.Row | None:
    checks = [
        ("status_id", parsed.status_id),
        ("original_url", parsed.original_url),
        ("source_url", parsed.source_url),
        ("file_path", parsed.file_path),
    ]
    for field, value in checks:
        if value:
            row = conn.execute(f"SELECT * FROM posts WHERE {field} = ?", (value,)).fetchone()
            if row:
                return row
    return None


def _is_retruth(parsed: ParsedPost) -> bool:
    text = f"{parsed.title or ''} {parsed.content_clean or ''}".lower()
    return text.startswith("rt ") or text.startswith("rt@") or "re-truth" in text
