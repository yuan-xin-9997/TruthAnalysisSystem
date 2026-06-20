from __future__ import annotations

import smtplib
from email.message import EmailMessage
from typing import Any

from app.config import Settings


def send_china_related_email(settings: Settings, posts: list[dict[str, Any]], task_summary: dict[str, Any]) -> dict[str, Any]:
    cfg = settings.notification
    if not cfg.enabled or not cfg.send_after_daily_crawl:
        return {"sent": False, "reason": "notification disabled"}
    if len(posts) < max(1, int(cfg.min_china_related_count)):
        return {"sent": False, "reason": "below threshold"}
    if not all([cfg.smtp_host, cfg.sender, cfg.recipient]):
        return {"sent": False, "reason": "smtp settings incomplete"}

    subject = f"{cfg.subject_prefix} 今日中国相关贴文 {len(posts)} 条"
    body = _build_body(posts, task_summary)
    msg = EmailMessage()
    msg["Subject"] = subject
    msg["From"] = cfg.sender
    msg["To"] = cfg.recipient
    msg.set_content(body)

    with smtplib.SMTP(cfg.smtp_host, int(cfg.smtp_port), timeout=20) as smtp:
        if cfg.smtp_use_tls:
            smtp.starttls()
        if cfg.smtp_username:
            smtp.login(cfg.smtp_username, cfg.smtp_password)
        smtp.send_message(msg)

    return {"sent": True, "count": len(posts), "subject": subject}


def send_test_email(settings: Settings) -> dict[str, Any]:
    cfg = settings.notification
    if not cfg.enabled:
        return {"sent": False, "reason": "notification disabled"}
    if not all([cfg.smtp_host, cfg.sender, cfg.recipient]):
        return {"sent": False, "reason": "smtp settings incomplete"}

    subject = f"{cfg.subject_prefix} 测试邮件"
    body = (
        "这是一封测试邮件，用于验证 SMTP 配置是否正确。\n\n"
        f"发件人：{cfg.sender}\n"
        f"收件人：{cfg.recipient}\n"
        f"SMTP：{cfg.smtp_host}:{cfg.smtp_port}\n"
    )
    msg = EmailMessage()
    msg["Subject"] = subject
    msg["From"] = cfg.sender
    msg["To"] = cfg.recipient
    msg.set_content(body)

    with smtplib.SMTP(cfg.smtp_host, int(cfg.smtp_port), timeout=20) as smtp:
        if cfg.smtp_use_tls:
            smtp.starttls()
        if cfg.smtp_username:
            smtp.login(cfg.smtp_username, cfg.smtp_password)
        smtp.send_message(msg)

    return {"sent": True, "subject": subject}


def _build_body(posts: list[dict[str, Any]], task_summary: dict[str, Any]) -> str:
    lines: list[str] = []
    lines.append("每日定时抓取完成，检测到中国相关贴文。")
    lines.append("")
    lines.append(f"抓取贴文数：{task_summary.get('saved', 0)}")
    lines.append(f"中国相关命中：{len(posts)}")
    lines.append("")
    for idx, post in enumerate(posts, start=1):
        lines.append(f"=== {idx}. {post.get('title') or ''} ===")
        lines.append(f"ID: {post.get('id')}")
        lines.append(f"发布时间: {post.get('published_date') or post.get('published_at_utc') or ''}")
        lines.append(f"相关性分数: {post.get('score')}")
        lines.append(f"命中关键词: {post.get('matched_keywords') or ''}")
        lines.append(f"原因: {post.get('reason') or ''}")
        lines.append(f"链接: {post.get('source_url') or post.get('original_url') or ''}")
        lines.append("")
        lines.append("正文：")
        lines.append(post.get("content_clean") or "")
        lines.append("")
        if post.get("file_path"):
            lines.append(f"Markdown: {post.get('file_path')}")
        lines.append("")
    return "\n".join(lines)
