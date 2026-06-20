from __future__ import annotations

import smtplib
from html import escape
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
    sorted_posts = sorted(
        posts,
        key=lambda post: (
            str(post.get("published_date") or post.get("published_at_utc") or ""),
            int(post.get("id") or 0),
        ),
        reverse=True,
    )
    plain_body, html_body = _build_message_bodies(sorted_posts, task_summary)
    msg = EmailMessage()
    msg["Subject"] = subject
    msg["From"] = cfg.sender
    msg["To"] = cfg.recipient
    msg.set_content(plain_body)
    msg.add_alternative(html_body, subtype="html")

    _send_via_smtp(cfg, msg)

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
    html_body = (
        "<html><body>"
        "<p>这是一封测试邮件，用于验证 SMTP 配置是否正确。</p>"
        f"<p>发件人：{escape(cfg.sender)}</p>"
        f"<p>收件人：{escape(cfg.recipient)}</p>"
        f"<p>SMTP：{escape(cfg.smtp_host)}:{cfg.smtp_port}</p>"
        "</body></html>"
    )
    msg = EmailMessage()
    msg["Subject"] = subject
    msg["From"] = cfg.sender
    msg["To"] = cfg.recipient
    msg.set_content(body)
    msg.add_alternative(html_body, subtype="html")

    _send_via_smtp(cfg, msg)

    return {"sent": True, "subject": subject}


def _send_via_smtp(cfg: Any, msg: EmailMessage) -> None:
    port = int(cfg.smtp_port)
    if port == 465:
        with smtplib.SMTP_SSL(cfg.smtp_host, port, timeout=20) as smtp:
            if cfg.smtp_username:
                smtp.login(cfg.smtp_username, cfg.smtp_password)
            smtp.send_message(msg)
        return
    with smtplib.SMTP(cfg.smtp_host, port, timeout=20) as smtp:
        if cfg.smtp_use_tls:
            smtp.starttls()
        if cfg.smtp_username:
            smtp.login(cfg.smtp_username, cfg.smtp_password)
        smtp.send_message(msg)


def _build_message_bodies(posts: list[dict[str, Any]], task_summary: dict[str, Any]) -> tuple[str, str]:
    plain_lines: list[str] = []
    plain_lines.append("每日定时抓取完成，检测到中国相关贴文。")
    plain_lines.append("")
    plain_lines.append(f"抓取贴文数：{task_summary.get('saved', 0)}")
    plain_lines.append(f"中国相关命中：{len(posts)}")
    plain_lines.append("")

    html_parts: list[str] = []
    html_parts.append("<html><body>")
    html_parts.append("<p>每日定时抓取完成，检测到中国相关贴文。</p>")
    html_parts.append(f"<p>抓取贴文数：{escape(str(task_summary.get('saved', 0)))}</p>")
    html_parts.append(f"<p>中国相关命中：{escape(str(len(posts)))}</p>")

    for idx, post in enumerate(posts, start=1):
        title = post.get("title") or ""
        published = post.get("published_date") or post.get("published_at_utc") or ""
        score = post.get("score")
        keywords = post.get("matched_keywords") or ""
        reason = post.get("reason") or ""
        link = post.get("source_url") or post.get("original_url") or ""
        body = post.get("content_clean") or ""
        markdown_path = post.get("file_path") or ""

        plain_lines.append(f"=== {idx}. {title} ===")
        plain_lines.append(f"ID: {post.get('id')}")
        plain_lines.append(f"发布时间: {published}")
        plain_lines.append(f"相关性分数: {score}")
        plain_lines.append(f"命中关键词: {keywords}")
        plain_lines.append(f"原因: {reason}")
        plain_lines.append(f"链接: {link}")
        plain_lines.append("")
        plain_lines.append("正文：")
        plain_lines.append(body)
        plain_lines.append("")
        if markdown_path:
            plain_lines.append(f"Markdown: {markdown_path}")
        plain_lines.append("")

        html_parts.append("<hr>")
        html_parts.append(f"<h3>{idx}. {escape(title)}</h3>")
        html_parts.append("<ul>")
        html_parts.append(f"<li><strong>ID:</strong> {escape(str(post.get('id')))}</li>")
        html_parts.append(f"<li><strong>发布时间:</strong> {escape(str(published))}</li>")
        html_parts.append(f"<li><strong>相关性分数:</strong> {escape(str(score))}</li>")
        html_parts.append(f"<li><strong>命中关键词:</strong> {escape(str(keywords))}</li>")
        html_parts.append(f"<li><strong>原因:</strong> {escape(str(reason))}</li>")
        html_parts.append(f"<li><strong>链接:</strong> <a href=\"{escape(str(link))}\">{escape(str(link))}</a></li>")
        if markdown_path:
            html_parts.append(f"<li><strong>Markdown:</strong> {escape(str(markdown_path))}</li>")
        html_parts.append("</ul>")
        html_parts.append(f"<p><strong>正文：</strong></p><pre style=\"white-space: pre-wrap; font-family: inherit;\">{escape(body)}</pre>")

    html_parts.append("</body></html>")
    return "\n".join(plain_lines), "".join(html_parts)
