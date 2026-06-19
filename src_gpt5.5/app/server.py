from __future__ import annotations

import json
import logging
import mimetypes
import re
from dataclasses import dataclass
from http import HTTPStatus
from http.cookies import SimpleCookie
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, quote, unquote, urlparse

from app.config import SRC_ROOT, Settings, public_settings
from app.db import connect, rows_to_dicts
from app.services import auth_service
from app.services.auth_service import ALL_PAGES, CurrentUser
from app.services.crawler_service import read_progress
from app.services.llm_analyzer import OpenAIAnalyzer
from app.services.task_manager import TaskManager


access_logger = logging.getLogger("app.server.access")


WEB_ROOT = SRC_ROOT / "app" / "web"
MEDIA_EXTENSIONS = {".jpg", ".jpeg", ".png", ".gif", ".webp", ".mp4", ".mov", ".webm"}
IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".gif", ".webp"}
VIDEO_EXTENSIONS = {".mp4", ".mov", ".webm"}
NOISE_TOPICS = {"Truth Social 平台"}
NOISE_TOPIC_SQL = "'Truth Social 平台'"
SESSION_COOKIE = "sid"
SESSION_MAX_AGE = 7 * 24 * 60 * 60  # seconds; matches auth_service.SESSION_TTL_DAYS
WORD_FREQUENCY_EXCLUDE = {
    "http",
    "https",
    "www",
    "com",
    "org",
    "net",
    "html",
    "truthsocial",
    "truth",
    "social",
    "status",
    "statuses",
    "users",
    "user",
    "link",
    "utm",
    "amp",
    "nbsp",
}


@dataclass
class AppContext:
    settings: Settings
    task_manager: TaskManager


class RequestHandler(BaseHTTPRequestHandler):
    context: AppContext

    def do_GET(self) -> None:  # noqa: N802
        parsed = urlparse(self.path)
        if parsed.path.startswith("/api/"):
            self._handle_api_get(parsed.path, parse_qs(parsed.query))
        else:
            self._serve_static(parsed.path)

    def do_PUT(self) -> None:  # noqa: N802
        parsed = urlparse(self.path)
        body = self._read_json_body()
        try:
            user = self._authenticate_or_401()
            if user is None:
                return
            if match := re.fullmatch(r"/api/users/(\d+)/pages", parsed.path):
                if not self._require_admin(user):
                    return
                self._handle_set_user_pages(int(match.group(1)), body)
            else:
                self._json({"error": "Not found"}, HTTPStatus.NOT_FOUND)
        except Exception as exc:  # noqa: BLE001
            self._json({"error": str(exc)}, HTTPStatus.INTERNAL_SERVER_ERROR)

    def do_POST(self) -> None:  # noqa: N802
        parsed = urlparse(self.path)
        body = self._read_json_body()
        try:
            # Auth endpoints handle their own authentication semantics.
            if parsed.path == "/api/auth/login":
                self._handle_login(body)
                return
            if parsed.path == "/api/auth/logout":
                self._handle_logout()
                return

            user = self._authenticate_or_401()
            if user is None:
                return

            if parsed.path == "/api/tasks/crawl":
                if not self._enforce_page(user, "crawler"):
                    return
                task_id = self.context.task_manager.start_task("crawl", parameters=body)
                self._json({"task_id": task_id})
            elif parsed.path == "/api/tasks/import":
                if not self._enforce_page(user, "tasks"):
                    return
                task_id = self.context.task_manager.start_task("import", parameters=body)
                self._json({"task_id": task_id})
            elif parsed.path == "/api/tasks/analyze":
                if not self._enforce_page(user, "tasks"):
                    return
                task_id = self.context.task_manager.start_task("analyze", parameters=body)
                self._json({"task_id": task_id})
            elif parsed.path == "/api/tasks/market-sync":
                if not self._enforce_page(user, "market"):
                    return
                task_id = self.context.task_manager.start_task("market_sync", parameters=body)
                self._json({"task_id": task_id})
            elif parsed.path == "/api/tasks/backtest":
                if not self._enforce_page(user, "market"):
                    return
                task_id = self.context.task_manager.start_task("backtest", parameters=body)
                self._json({"task_id": task_id})
            elif parsed.path == "/api/tasks/predict":
                if not self._enforce_page(user, "market"):
                    return
                task_id = self.context.task_manager.start_task("predict", parameters=body)
                self._json({"task_id": task_id})
            elif parsed.path == "/api/tasks/daily-chain":
                if not self._enforce_page(user, "tasks"):
                    return
                task_id = self.context.task_manager.start_task("daily_chain", parameters=body)
                self._json({"task_id": task_id})
            elif parsed.path == "/api/analysis/summary":
                if not self._enforce_page(user, "analysis"):
                    return
                self._json(self._llm_summary(body))
            else:
                self._json({"error": "Not found"}, HTTPStatus.NOT_FOUND)
        except Exception as exc:  # noqa: BLE001
            self._json({"error": str(exc)}, HTTPStatus.INTERNAL_SERVER_ERROR)

    def log_message(self, fmt: str, *args: Any) -> None:
        access_logger.info("%s - %s", self.address_string(), fmt % args)

    def _handle_api_get(self, path: str, query: dict[str, list[str]]) -> None:
        try:
            # /api/auth/me is special: it returns the current user or 401, but
            # never redirects.
            if path == "/api/auth/me":
                self._handle_me()
                return

            user = self._authenticate_or_401()
            if user is None:
                return

            if path == "/api/dashboard/summary":
                if not self._enforce_page(user, "dashboard"):
                    return
                self._json(api_dashboard_summary(self.context.settings))
            elif path == "/api/dashboard/timeline":
                if not self._enforce_page(user, "dashboard"):
                    return
                self._json(api_timeline(self.context.settings, query))
            elif path == "/api/dashboard/top-entities":
                if not self._enforce_page(user, "dashboard"):
                    return
                self._json(api_top_entities(self.context.settings, query))
            elif path == "/api/dashboard/recent-posts":
                if not self._enforce_page(user, "dashboard"):
                    return
                self._json(api_posts(self.context.settings, {"page_size": ["10"]}))
            elif path == "/api/posts":
                if not self._enforce_page(user, "posts"):
                    return
                self._json(api_posts(self.context.settings, query))
            elif match := re.fullmatch(r"/api/posts/(\d+)", path):
                if not self._enforce_page(user, "posts"):
                    return
                self._json(api_post_detail(self.context.settings, int(match.group(1))))
            elif match := re.fullmatch(r"/api/posts/(\d+)/analysis", path):
                if not self._enforce_page(user, "posts"):
                    return
                self._json(api_post_analysis(self.context.settings, int(match.group(1))))
            elif match := re.fullmatch(r"/api/media/(\d+)/([^/]+)", path):
                if not self._enforce_page(user, "posts"):
                    return
                self._serve_media_file(int(match.group(1)), match.group(2))
            elif path == "/api/analysis/word-frequency":
                if not self._enforce_page(user, "analysis"):
                    return
                self._json(api_word_frequency(self.context.settings, query))
            elif path == "/api/analysis/overview":
                if not self._enforce_page(user, "analysis"):
                    return
                self._json(api_analysis_overview(self.context.settings, query))
            elif path == "/api/analysis/top-topics":
                if not self._enforce_page(user, "analysis"):
                    return
                self._json(api_top_topics(self.context.settings, query))
            elif path == "/api/analysis/entities":
                if not self._enforce_page(user, "analysis"):
                    return
                self._json(api_analysis_entities(self.context.settings, query))
            elif path == "/api/analysis/representative-posts":
                if not self._enforce_page(user, "analysis"):
                    return
                self._json(api_representative_posts(self.context.settings, query))
            elif path == "/api/analysis/topics/trend":
                if not self._enforce_page(user, "analysis"):
                    return
                self._json(api_topic_trend(self.context.settings, query))
            elif path == "/api/analysis/countries":
                if not self._enforce_page(user, "analysis"):
                    return
                self._json(api_countries(self.context.settings, query))
            elif path == "/api/analysis/china":
                if not self._enforce_page(user, "analysis"):
                    return
                self._json(api_china(self.context.settings, query))
            elif path == "/api/analysis/sentiment":
                if not self._enforce_page(user, "analysis"):
                    return
                self._json(api_sentiment(self.context.settings, query))
            elif path == "/api/tasks":
                if not self._enforce_page(user, "tasks"):
                    return
                self._json(api_tasks(self.context.settings, query))
            elif match := re.fullmatch(r"/api/tasks/(\d+)/logs", path):
                if not self._enforce_page(user, "tasks"):
                    return
                self._json(api_task_logs(self.context.settings, int(match.group(1))))
            elif path == "/api/crawler/status":
                if not self._enforce_page(user, "crawler"):
                    return
                self._json(api_crawler_status(self.context.settings))
            elif path == "/api/market/backtests":
                if not self._enforce_page(user, "market"):
                    return
                self._json(api_backtests(self.context.settings))
            elif path == "/api/market/predictions":
                if not self._enforce_page(user, "market"):
                    return
                self._json(api_predictions(self.context.settings))
            elif path == "/api/settings":
                if not self._enforce_page(user, "settings"):
                    return
                self._json(public_settings(self.context.settings))
            elif path == "/api/settings/health":
                if not self._enforce_page(user, "settings"):
                    return
                self._json(api_health(self.context.settings))
            elif path == "/api/users":
                if not self._require_admin(user):
                    return
                with connect(self.context.settings.paths.database) as conn:
                    items = auth_service.list_users(conn, self.context.settings.paths.password_file)
                self._json({"items": items})
            elif path == "/api/permissions/pages":
                if not self._require_admin(user):
                    return
                self._json({"items": list(ALL_PAGES)})
            else:
                self._json({"error": "Not found"}, HTTPStatus.NOT_FOUND)
        except Exception as exc:  # noqa: BLE001
            self._json({"error": str(exc)}, HTTPStatus.INTERNAL_SERVER_ERROR)

    def _serve_media_file(self, source_status_id: int, filename: str) -> None:
        safe_name = Path(unquote(filename)).name
        target = None
        for directory in self.context.settings.paths.content_root.rglob(f"attachments/{source_status_id}"):
            candidate = directory / safe_name
            if candidate.is_file():
                target = candidate
                break
        if not target:
            self.send_error(HTTPStatus.NOT_FOUND)
            return
        mime = mimetypes.guess_type(str(target))[0] or "application/octet-stream"
        data = target.read_bytes()
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", mime)
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    # --- auth helpers -------------------------------------------------------

    def _read_session_token(self) -> str | None:
        cookie_header = self.headers.get("Cookie")
        if not cookie_header:
            return None
        try:
            jar = SimpleCookie(cookie_header)
        except Exception:  # noqa: BLE001
            return None
        morsel = jar.get(SESSION_COOKIE)
        return morsel.value if morsel else None

    def _current_user(self) -> CurrentUser | None:
        token = self._read_session_token()
        if not token:
            return None
        with connect(self.context.settings.paths.database) as conn:
            return auth_service.get_session(conn, token)

    def _authenticate_or_401(self) -> CurrentUser | None:
        user = self._current_user()
        if user is None:
            self._json({"error": "Unauthorized"}, HTTPStatus.UNAUTHORIZED)
            return None
        return user

    def _enforce_page(self, user: CurrentUser, page: str) -> bool:
        if user.can_access(page):
            return True
        self._json(
            {"error": f"Forbidden: missing access to '{page}'"},
            HTTPStatus.FORBIDDEN,
        )
        return False

    def _require_admin(self, user: CurrentUser) -> bool:
        if user.is_admin:
            return True
        self._json({"error": "Forbidden: admin only"}, HTTPStatus.FORBIDDEN)
        return False

    def _handle_login(self, body: dict[str, Any]) -> None:
        username = (body.get("username") or "").strip()
        password = body.get("password") or ""
        if not username or not password:
            self._json({"error": "用户名和密码不能为空"}, HTTPStatus.BAD_REQUEST)
            return
        with connect(self.context.settings.paths.database) as conn:
            result = auth_service.login(
                conn, self.context.settings.paths.password_file, username, password
            )
        if not result:
            self._json({"error": "用户名或密码错误"}, HTTPStatus.UNAUTHORIZED)
            return
        token, user = result
        payload = {
            "user": {
                "username": user.username,
                "role": user.role,
                "pages": sorted(user.pages),
            }
        }
        self._json_with_cookie(payload, token=token)

    def _handle_logout(self) -> None:
        token = self._read_session_token()
        if token:
            with connect(self.context.settings.paths.database) as conn:
                auth_service.logout(conn, token)
        self._json_with_cookie({"ok": True}, clear_cookie=True)

    def _handle_me(self) -> None:
        user = self._current_user()
        if user is None:
            self._json({"error": "Unauthorized"}, HTTPStatus.UNAUTHORIZED)
            return
        self._json(
            {
                "username": user.username,
                "role": user.role,
                "pages": sorted(user.pages),
            }
        )

    def _handle_set_user_pages(self, user_id: int, body: dict[str, Any]) -> None:
        pages = body.get("pages")
        if not isinstance(pages, list):
            self._json({"error": "pages must be a list"}, HTTPStatus.BAD_REQUEST)
            return
        try:
            with connect(self.context.settings.paths.database) as conn:
                auth_service.set_user_pages(conn, user_id, pages)
        except ValueError as exc:
            self._json({"error": str(exc)}, HTTPStatus.BAD_REQUEST)
            return
        self._json({"ok": True})

    # --- end auth helpers ---------------------------------------------------

    def _serve_static(self, path: str) -> None:
        if path in {"", "/"}:
            target = WEB_ROOT / "index.html"
        else:
            clean = path.lstrip("/").replace("..", "")
            target = WEB_ROOT / clean
            if not target.exists():
                target = WEB_ROOT / "index.html"
        if not target.exists() or not target.is_file():
            self.send_error(HTTPStatus.NOT_FOUND)
            return
        mime = mimetypes.guess_type(str(target))[0] or "application/octet-stream"
        data = target.read_bytes()
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", f"{mime}; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def _json(self, data: Any, status: HTTPStatus = HTTPStatus.OK) -> None:
        payload = json.dumps(data, ensure_ascii=False, default=str).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def _json_with_cookie(
        self,
        data: Any,
        *,
        status: HTTPStatus = HTTPStatus.OK,
        token: str | None = None,
        clear_cookie: bool = False,
    ) -> None:
        payload = json.dumps(data, ensure_ascii=False, default=str).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(payload)))
        if clear_cookie:
            self.send_header(
                "Set-Cookie",
                f"{SESSION_COOKIE}=; HttpOnly; Path=/; SameSite=Lax; Max-Age=0",
            )
        elif token is not None:
            self.send_header(
                "Set-Cookie",
                f"{SESSION_COOKIE}={token}; HttpOnly; Path=/; SameSite=Lax; Max-Age={SESSION_MAX_AGE}",
            )
        self.end_headers()
        self.wfile.write(payload)

    def _read_json_body(self) -> dict[str, Any]:
        length = int(self.headers.get("Content-Length") or 0)
        if length <= 0:
            return {}
        raw = self.rfile.read(length).decode("utf-8")
        return json.loads(raw) if raw.strip() else {}

    def _llm_summary(self, body: dict[str, Any]) -> dict[str, Any]:
        analyzer = OpenAIAnalyzer(model=self.context.settings.analysis.openai_model)
        if not analyzer.available:
            return {"error": "OPENAI_API_KEY is not set"}
        query: dict[str, list[str]] = {}
        if body.get("date_from"):
            query["date_from"] = [body["date_from"]]
        if body.get("date_to"):
            query["date_to"] = [body["date_to"]]
        posts = api_posts(self.context.settings, {**query, "page_size": ["60"]})["items"]
        return analyzer.summarize_range(posts)


def make_server(settings: Settings, task_manager: TaskManager) -> ThreadingHTTPServer:
    RequestHandler.context = AppContext(settings=settings, task_manager=task_manager)
    return ThreadingHTTPServer((settings.app.host, settings.app.port), RequestHandler)


def api_dashboard_summary(settings: Settings) -> dict[str, Any]:
    with connect(settings.paths.database) as conn:
        total = conn.execute("SELECT COUNT(*) AS c FROM posts").fetchone()["c"]
        latest = conn.execute("SELECT MAX(published_at_utc) AS v FROM posts").fetchone()["v"]
        first = conn.execute("SELECT MIN(published_at_utc) AS v FROM posts").fetchone()["v"]
        china = conn.execute(
            "SELECT COUNT(*) AS c FROM post_china_relevance WHERE is_related = 1"
        ).fetchone()["c"]
        market = conn.execute("SELECT COUNT(*) AS c FROM post_market_signals").fetchone()["c"]
        running = conn.execute("SELECT COUNT(*) AS c FROM tasks WHERE status = 'running'").fetchone()["c"]
        return {
            "total_posts": total,
            "first_post": first,
            "latest_post": latest,
            "china_related": china,
            "china_ratio": china / total if total else 0,
            "market_related": market,
            "running_tasks": running,
        }


def api_posts(settings: Settings, query: dict[str, list[str]]) -> dict[str, Any]:
    page = int(_one(query, "page", "1"))
    page_size = min(100, int(_one(query, "page_size", "25")))
    where, params = _post_filters(query)
    order_sql = _post_order(query)
    offset = (page - 1) * page_size
    sql = f"""
        SELECT p.*,
               c.is_related AS china_related,
               c.score AS china_score,
               s.polarity AS sentiment,
               group_concat(DISTINCT t.topic) AS topics
        FROM posts p
        LEFT JOIN post_china_relevance c ON c.post_id = p.id
        LEFT JOIN post_sentiments s ON s.post_id = p.id
        LEFT JOIN post_topics t ON t.post_id = p.id AND t.topic NOT IN ({NOISE_TOPIC_SQL})
        {where}
        GROUP BY p.id
        ORDER BY {order_sql}
        LIMIT ? OFFSET ?
    """
    count_sql = f"SELECT COUNT(*) AS c FROM posts p {where}"
    with connect(settings.paths.database) as conn:
        total = conn.execute(count_sql, params).fetchone()["c"]
        rows = conn.execute(sql, (*params, page_size, offset)).fetchall()
    return {"items": rows_to_dicts(rows), "total": total, "page": page, "page_size": page_size}


def api_post_detail(settings: Settings, post_id: int) -> dict[str, Any]:
    with connect(settings.paths.database) as conn:
        post = conn.execute("SELECT * FROM posts WHERE id = ?", (post_id,)).fetchone()
        if not post:
            return {"error": "Post not found"}
        attachments = conn.execute(
            "SELECT * FROM post_attachments WHERE post_id = ?", (post_id,)
        ).fetchall()
    post_dict = dict(post)
    attachment_items = _enrich_attachments(settings, post_dict, rows_to_dicts(attachments))
    return {"post": post_dict, "attachments": attachment_items}


def api_post_analysis(settings: Settings, post_id: int) -> dict[str, Any]:
    with connect(settings.paths.database) as conn:
        terms = conn.execute(
            "SELECT term, count FROM post_terms WHERE post_id = ? ORDER BY count DESC LIMIT 50",
            (post_id,),
        ).fetchall()
        entities = conn.execute(
            "SELECT * FROM post_entities WHERE post_id = ? ORDER BY confidence DESC",
            (post_id,),
        ).fetchall()
        topics = conn.execute(
            f"SELECT * FROM post_topics WHERE post_id = ? AND topic NOT IN ({NOISE_TOPIC_SQL}) ORDER BY confidence DESC",
            (post_id,),
        ).fetchall()
        china = conn.execute(
            "SELECT * FROM post_china_relevance WHERE post_id = ?", (post_id,)
        ).fetchone()
        sentiment = conn.execute(
            "SELECT * FROM post_sentiments WHERE post_id = ? ORDER BY id DESC LIMIT 1",
            (post_id,),
        ).fetchone()
        signals = conn.execute(
            "SELECT * FROM post_market_signals WHERE post_id = ?", (post_id,)
        ).fetchall()
    return {
        "terms": rows_to_dicts(terms),
        "entities": rows_to_dicts(entities),
        "topics": rows_to_dicts(topics),
        "china": dict(china) if china else None,
        "sentiment": dict(sentiment) if sentiment else None,
        "market_signals": rows_to_dicts(signals),
    }


def api_timeline(settings: Settings, query: dict[str, list[str]]) -> dict[str, Any]:
    where, params = _date_filters(query)
    with connect(settings.paths.database) as conn:
        rows = conn.execute(
            f"""
            SELECT published_date AS date, COUNT(*) AS count
            FROM posts p
            {where}
            GROUP BY published_date
            ORDER BY published_date
            """,
            params,
        ).fetchall()
    return {"items": rows_to_dicts(rows)}


def api_top_entities(settings: Settings, query: dict[str, list[str]]) -> dict[str, Any]:
    with connect(settings.paths.database) as conn:
        rows = conn.execute(
            """
            SELECT normalized_name, entity_type, COUNT(*) AS count
            FROM post_entities
            GROUP BY normalized_name, entity_type
            ORDER BY count DESC
            LIMIT 30
            """
        ).fetchall()
    return {"items": rows_to_dicts(rows)}


def api_word_frequency(settings: Settings, query: dict[str, list[str]]) -> dict[str, Any]:
    placeholders = ", ".join("?" for _ in WORD_FREQUENCY_EXCLUDE)
    where, params = _analysis_post_filters(query, alias="p")
    with connect(settings.paths.database) as conn:
        rows = conn.execute(
            f"""
            SELECT term, SUM(count) AS count
            FROM post_terms
            JOIN posts p ON p.id = post_terms.post_id
            LEFT JOIN post_sentiments s ON s.post_id = p.id
            {where}
            {"AND" if where else "WHERE"} term NOT IN ({placeholders})
              AND length(term) >= 3
              AND term NOT GLOB '*[0-9]*'
              AND term NOT GLOB '*_*'
            GROUP BY term
            ORDER BY count DESC
            LIMIT 80
            """,
            (*params, *tuple(WORD_FREQUENCY_EXCLUDE)),
        ).fetchall()
    return {"items": rows_to_dicts(rows)}


def api_analysis_overview(settings: Settings, query: dict[str, list[str]]) -> dict[str, Any]:
    where, params = _analysis_post_filters(query, alias="p")
    with connect(settings.paths.database) as conn:
        summary = conn.execute(
            f"""
            SELECT
              COUNT(DISTINCT p.id) AS posts,
              COUNT(DISTINCT CASE WHEN c.is_related = 1 THEN p.id END) AS china_related,
              COUNT(DISTINCT m.post_id) AS market_related,
              COUNT(DISTINCT CASE WHEN s.polarity = 'positive' THEN p.id END) AS positive,
              COUNT(DISTINCT CASE WHEN s.polarity = 'neutral' THEN p.id END) AS neutral,
              COUNT(DISTINCT CASE WHEN s.polarity = 'negative' THEN p.id END) AS negative,
              AVG(s.score) AS avg_sentiment
            FROM posts p
            LEFT JOIN post_china_relevance c ON c.post_id = p.id
            LEFT JOIN post_market_signals m ON m.post_id = p.id
            LEFT JOIN post_sentiments s ON s.post_id = p.id
            {where}
            """,
            params,
        ).fetchone()
    return {"summary": dict(summary)}


def api_top_topics(settings: Settings, query: dict[str, list[str]]) -> dict[str, Any]:
    where, params = _analysis_post_filters(query, alias="p", include_topic=False)
    with connect(settings.paths.database) as conn:
        rows = conn.execute(
            f"""
            SELECT t.topic, COUNT(DISTINCT p.id) AS count, AVG(t.confidence) AS avg_confidence
            FROM post_topics t
            JOIN posts p ON p.id = t.post_id
            LEFT JOIN post_sentiments s ON s.post_id = p.id
            {where}
            {"AND" if where else "WHERE"} t.topic NOT IN ({NOISE_TOPIC_SQL})
            GROUP BY t.topic
            ORDER BY count DESC, avg_confidence DESC
            LIMIT 20
            """,
            params,
        ).fetchall()
    return {"items": rows_to_dicts(rows)}


def api_analysis_entities(settings: Settings, query: dict[str, list[str]]) -> dict[str, Any]:
    where, params = _analysis_post_filters(query, alias="p")
    entity_type = _one(query, "entity_type")
    extra = ""
    extra_params: list[Any] = []
    if entity_type:
        extra = " AND e.entity_type = ?" if where else " WHERE e.entity_type = ?"
        extra_params.append(entity_type)
    with connect(settings.paths.database) as conn:
        rows = conn.execute(
            f"""
            SELECT
              e.normalized_name,
              e.entity_type,
              COUNT(DISTINCT p.id) AS count,
              MAX(p.published_date) AS latest_date,
              AVG(s.score) AS avg_sentiment
            FROM post_entities e
            JOIN posts p ON p.id = e.post_id
            LEFT JOIN post_sentiments s ON s.post_id = p.id
            {where}
            {extra}
            GROUP BY e.normalized_name, e.entity_type
            ORDER BY count DESC, latest_date DESC
            LIMIT 40
            """,
            (*params, *extra_params),
        ).fetchall()
    return {"items": rows_to_dicts(rows)}


def api_representative_posts(settings: Settings, query: dict[str, list[str]]) -> dict[str, Any]:
    where, params = _analysis_post_filters(query, alias="p")
    with connect(settings.paths.database) as conn:
        rows = conn.execute(
            f"""
            SELECT p.id, p.published_date, p.published_at_raw, p.title, p.content_clean,
                   s.polarity AS sentiment, s.score AS sentiment_score,
                   group_concat(DISTINCT t.topic) AS topics
            FROM posts p
            LEFT JOIN post_sentiments s ON s.post_id = p.id
            LEFT JOIN post_topics t ON t.post_id = p.id AND t.topic NOT IN ({NOISE_TOPIC_SQL})
            {where}
            GROUP BY p.id
            ORDER BY p.published_at_utc DESC, p.id DESC
            LIMIT 30
            """,
            params,
        ).fetchall()
    return {"items": rows_to_dicts(rows)}


def api_topic_trend(settings: Settings, query: dict[str, list[str]]) -> dict[str, Any]:
    where, params = _analysis_post_filters(query, alias="p", include_topic=False)
    topic = _one(query, "topic")
    topic_filter = ""
    topic_params: list[Any] = []
    if topic:
        topic_filter = " AND t.topic = ?" if where else " WHERE t.topic = ?"
        topic_params.append(topic)
    with connect(settings.paths.database) as conn:
        rows = conn.execute(
            f"""
            SELECT p.published_date AS date, t.topic, COUNT(*) AS count
            FROM post_topics t
            JOIN posts p ON p.id = t.post_id
            LEFT JOIN post_sentiments s ON s.post_id = p.id
            {where}
            {topic_filter}
            {"AND" if where or topic_filter else "WHERE"} t.topic NOT IN ({NOISE_TOPIC_SQL})
            GROUP BY p.published_date, t.topic
            ORDER BY p.published_date
            """,
            (*params, *topic_params),
        ).fetchall()
    return {"items": rows_to_dicts(rows)}


def api_countries(settings: Settings, query: dict[str, list[str]]) -> dict[str, Any]:
    where, params = _analysis_post_filters(query, alias="p")
    country_clause = " AND post_entities.entity_type = 'country'" if where else "WHERE post_entities.entity_type = 'country'"
    with connect(settings.paths.database) as conn:
        rows = conn.execute(
            f"""
            SELECT normalized_name AS country, COUNT(DISTINCT p.id) AS count
            FROM post_entities
            JOIN posts p ON p.id = post_entities.post_id
            LEFT JOIN post_sentiments s ON s.post_id = p.id
            {where}
            {country_clause}
            GROUP BY normalized_name
            ORDER BY count DESC
            LIMIT 25
            """,
            params,
        ).fetchall()
    return {"items": rows_to_dicts(rows)}


def api_china(settings: Settings, query: dict[str, list[str]]) -> dict[str, Any]:
    where, params = _analysis_post_filters(query, alias="p")
    related_clause = " AND c.is_related = 1" if where else "WHERE c.is_related = 1"
    with connect(settings.paths.database) as conn:
        summary = conn.execute(
            f"""
            SELECT
              SUM(CASE WHEN c.is_related = 1 THEN 1 ELSE 0 END) AS related,
              COUNT(*) AS analyzed,
              AVG(c.score) AS avg_score
            FROM post_china_relevance c
            JOIN posts p ON p.id = c.post_id
            LEFT JOIN post_sentiments s ON s.post_id = p.id
            {where}
            """,
            params,
        ).fetchone()
        posts = conn.execute(
            f"""
            SELECT p.id, p.title, p.published_date, p.content_clean, c.score, c.matched_keywords, c.reason
            FROM post_china_relevance c
            JOIN posts p ON p.id = c.post_id
            LEFT JOIN post_sentiments s ON s.post_id = p.id
            {where}
            {related_clause}
            ORDER BY p.published_at_utc DESC
            LIMIT 30
            """,
            params,
        ).fetchall()
    return {"summary": dict(summary), "posts": rows_to_dicts(posts)}


def api_sentiment(settings: Settings, query: dict[str, list[str]]) -> dict[str, Any]:
    where, params = _analysis_post_filters(query, alias="p", include_sentiment=False)
    sentiment = _one(query, "sentiment")
    sentiment_clause = ""
    sentiment_params: list[Any] = []
    if sentiment:
        sentiment_clause = " AND s.polarity = ?" if where else "WHERE s.polarity = ?"
        sentiment_params.append(sentiment)
    with connect(settings.paths.database) as conn:
        rows = conn.execute(
            f"""
            SELECT p.published_date AS date, s.polarity, COUNT(*) AS count, AVG(s.score) AS avg_score
            FROM post_sentiments s
            JOIN posts p ON p.id = s.post_id
            {where}
            {sentiment_clause}
            GROUP BY p.published_date, s.polarity
            ORDER BY p.published_date
            """,
            (*params, *sentiment_params),
        ).fetchall()
    return {"items": rows_to_dicts(rows)}


def api_tasks(settings: Settings, query: dict[str, list[str]]) -> dict[str, Any]:
    with connect(settings.paths.database) as conn:
        rows = conn.execute(
            "SELECT * FROM tasks ORDER BY id DESC LIMIT 100"
        ).fetchall()
    return {"items": rows_to_dicts(rows)}


def api_task_logs(settings: Settings, task_id: int) -> dict[str, Any]:
    with connect(settings.paths.database) as conn:
        task = conn.execute("SELECT * FROM tasks WHERE id = ?", (task_id,)).fetchone()
        rows = conn.execute(
            "SELECT * FROM task_logs WHERE task_id = ? ORDER BY id", (task_id,)
        ).fetchall()
    return {"task": dict(task) if task else None, "items": rows_to_dicts(rows)}


def api_crawler_status(settings: Settings) -> dict[str, Any]:
    progress_path = settings.paths.content_root / settings.crawler.progress_file
    current_progress = read_progress(progress_path)
    with connect(settings.paths.database) as conn:
        last_crawl = conn.execute(
            "SELECT * FROM tasks WHERE task_type = 'crawl' ORDER BY id DESC LIMIT 1"
        ).fetchone()
        running = conn.execute(
            "SELECT COUNT(*) AS c FROM tasks WHERE task_type = 'crawl' AND status = 'running'"
        ).fetchone()["c"]
    return {
        "progress_file": str(progress_path),
        "content_root": str(settings.paths.content_root),
        "current_progress": current_progress,
        "default_start_after": current_progress,
        "default_batch_size": settings.crawler.batch_size,
        "base_url": settings.crawler.base_url,
        "daily_time": settings.crawler.daily_time,
        "request_timeout_seconds": settings.crawler.request_timeout_seconds,
        "request_delay_seconds": settings.crawler.request_delay_seconds,
        "max_workers": settings.crawler.max_workers,
        "download_attachments": settings.crawler.download_attachments,
        "translate_to_chinese": settings.crawler.translate_to_chinese,
        "running": running,
        "last_crawl": dict(last_crawl) if last_crawl else None,
    }


def api_backtests(settings: Settings) -> dict[str, Any]:
    with connect(settings.paths.database) as conn:
        rows = conn.execute("SELECT * FROM backtest_runs ORDER BY id DESC LIMIT 50").fetchall()
    return {"items": rows_to_dicts(rows)}


def api_predictions(settings: Settings) -> dict[str, Any]:
    with connect(settings.paths.database) as conn:
        rows = conn.execute(
            """
            SELECT pr.created_at, p.*
            FROM predictions p
            JOIN prediction_runs pr ON pr.id = p.prediction_run_id
            ORDER BY p.id DESC
            LIMIT 100
            """
        ).fetchall()
    return {"items": rows_to_dicts(rows)}


def api_health(settings: Settings) -> dict[str, Any]:
    return {
        "content_root_exists": settings.paths.content_root.exists(),
        "database_exists": settings.paths.database.exists(),
        "openai_key_present": bool(OpenAIAnalyzer(settings.analysis.openai_model).available),
        "listening_host": settings.app.host,
        "port": settings.app.port,
    }


def _post_filters(query: dict[str, list[str]]) -> tuple[str, tuple[Any, ...]]:
    clauses: list[str] = []
    params: list[Any] = []
    q = _one(query, "q")
    if q:
        clauses.append("(p.title LIKE ? OR p.content_clean LIKE ?)")
        params.extend([f"%{q}%", f"%{q}%"])
    date_from = _one(query, "date_from")
    if date_from:
        clauses.append("p.published_date >= ?")
        params.append(date_from)
    date_to = _one(query, "date_to")
    if date_to:
        clauses.append("p.published_date <= ?")
        params.append(date_to)
    china_related = _one(query, "china_related")
    if china_related in {"0", "1"}:
        clauses.append(
            "p.id IN (SELECT post_id FROM post_china_relevance WHERE is_related = ?)"
        )
        params.append(int(china_related))
    market_related = _one(query, "market_related")
    if market_related == "1":
        clauses.append("p.id IN (SELECT post_id FROM post_market_signals)")
    topic = _one(query, "topic")
    if topic:
        clauses.append("p.id IN (SELECT post_id FROM post_topics WHERE topic = ?)")
        params.append(topic)
    where = "WHERE " + " AND ".join(clauses) if clauses else ""
    return where, tuple(params)


def _post_order(query: dict[str, list[str]]) -> str:
    sort = (_one(query, "sort", "date") or "date").lower()
    order = (_one(query, "order", "desc") or "desc").lower()
    direction = "ASC" if order == "asc" else "DESC"
    if sort == "date":
        return f"p.published_at_utc {direction}, p.id {direction}"
    return "p.published_at_utc DESC, p.id DESC"


def _enrich_attachments(settings: Settings, post: dict[str, Any], attachments: list[dict[str, Any]]) -> list[dict[str, Any]]:
    enriched: list[dict[str, Any]] = []
    seen_urls: set[str] = set()

    for item in attachments:
        url = item.get("url") or ""
        if not _is_displayable_attachment(url, item.get("attachment_type")):
            continue
        if url in seen_urls:
            continue
        seen_urls.add(url)
        enriched.append(item)

    source_status_id = post.get("source_status_id")
    if source_status_id:
        for media_file in _local_media_files(settings.paths.content_root, int(source_status_id)):
            stat = media_file.stat()
            # Skip small site icons and tracking pixels; keep actual media and preview images.
            if stat.st_size < 10_000:
                continue
            suffix = media_file.suffix.lower()
            kind = "video" if suffix in VIDEO_EXTENSIONS else "image"
            local_item = {
                "id": f"local-{source_status_id}-{media_file.name}",
                "post_id": post.get("id"),
                "attachment_type": kind,
                "url": None,
                "local_path": str(media_file),
                "local_url": f"/api/media/{source_status_id}/{quote(media_file.name)}",
                "description": media_file.name,
                "raw_text": None,
            }
            if local_item["local_url"] not in seen_urls:
                enriched.append(local_item)
                seen_urls.add(local_item["local_url"])
    return enriched


def _local_media_files(content_root: Path, source_status_id: int) -> list[Path]:
    direct_matches = list(content_root.rglob(f"attachments/{source_status_id}"))
    files: list[Path] = []
    for directory in direct_matches:
        if directory.is_dir():
            files.extend(
                path
                for path in directory.iterdir()
                if path.is_file() and path.suffix.lower() in MEDIA_EXTENSIONS
            )
    return sorted(files, key=lambda path: path.name)


def _is_displayable_attachment(url: str, attachment_type: str | None) -> bool:
    if not url:
        return False
    lowered = url.lower()
    if "site-icons" in lowered or "accounts/avatars" in lowered:
        return False
    if attachment_type in {"image", "video"}:
        return True
    suffix = Path(urlparse(url).path).suffix.lower()
    return suffix in MEDIA_EXTENSIONS


def _analysis_post_filters(
    query: dict[str, list[str]],
    alias: str = "p",
    include_topic: bool = True,
    include_sentiment: bool = True,
) -> tuple[str, tuple[Any, ...]]:
    clauses: list[str] = []
    params: list[Any] = []
    if date_from := _one(query, "date_from"):
        clauses.append(f"{alias}.published_date >= ?")
        params.append(date_from)
    if date_to := _one(query, "date_to"):
        clauses.append(f"{alias}.published_date <= ?")
        params.append(date_to)
    if include_topic and (topic := _one(query, "topic")):
        clauses.append(f"{alias}.id IN (SELECT post_id FROM post_topics WHERE topic = ?)")
        params.append(topic)
    if include_sentiment and (sentiment := _one(query, "sentiment")):
        clauses.append("s.polarity = ?")
        params.append(sentiment)
    china_related = _one(query, "china_related")
    if china_related in {"0", "1"}:
        clauses.append(f"{alias}.id IN (SELECT post_id FROM post_china_relevance WHERE is_related = ?)")
        params.append(int(china_related))
    if _one(query, "market_related") == "1":
        clauses.append(f"{alias}.id IN (SELECT post_id FROM post_market_signals)")
    where = "WHERE " + " AND ".join(clauses) if clauses else ""
    return where, tuple(params)


def _date_filters(query: dict[str, list[str]]) -> tuple[str, tuple[Any, ...]]:
    clauses: list[str] = []
    params: list[Any] = []
    if date_from := _one(query, "date_from"):
        clauses.append("p.published_date >= ?")
        params.append(date_from)
    if date_to := _one(query, "date_to"):
        clauses.append("p.published_date <= ?")
        params.append(date_to)
    return ("WHERE " + " AND ".join(clauses) if clauses else "", tuple(params))


def _one(query: dict[str, list[str]], key: str, default: str | None = None) -> str | None:
    values = query.get(key)
    return values[0] if values else default
