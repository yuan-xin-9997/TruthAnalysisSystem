from __future__ import annotations

import hmac
import secrets
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Iterable


# Page keys correspond to nav buttons; the permissions page is admin-only and
# not configurable.
ALL_PAGES: tuple[str, ...] = (
    "dashboard",
    "crawler",
    "posts",
    "analysis",
    "market",
    "tasks",
    "settings",
)

DEFAULT_PASSWORD_FILE = """\
# 特朗普真实社交贴文分析系统 - 用户配置
# 格式: username:password:role  (role 取值: admin | user)
# admin 默认拥有所有页面权限；user 的可见页面由管理员在权限管理页配置。
# 修改本文件后，新用户在下次登录时会自动同步到数据库。
admin:admin123:admin
"""

SESSION_TTL_DAYS = 7


@dataclass(frozen=True)
class CurrentUser:
    id: int
    username: str
    role: str
    pages: frozenset[str]

    @property
    def is_admin(self) -> bool:
        return self.role == "admin"

    def can_access(self, page: str) -> bool:
        if self.is_admin:
            return True
        return page in self.pages


def parse_password_file(path: Path) -> dict[str, tuple[str, str]]:
    """Read ``data/password.txt``; return ``{username: (password, role)}``.

    Creates a default file with an ``admin/admin123`` line if missing. Lines
    starting with ``#`` and blank lines are skipped. Malformed lines are
    silently dropped (printed to stderr would be noisy in normal operation).
    """

    if not path.exists():
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(DEFAULT_PASSWORD_FILE, encoding="utf-8")

    users: dict[str, tuple[str, str]] = {}
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        parts = line.split(":", 2)
        if len(parts) != 3:
            continue
        username, password, role = parts[0].strip(), parts[1], parts[2].strip().lower()
        if not username or not password or role not in {"admin", "user"}:
            continue
        users[username] = (password, role)
    return users


def sync_users(conn: sqlite3.Connection, file_users: dict[str, tuple[str, str]]) -> None:
    """Sync users from password.txt into the ``users`` table.

    - Inserts new usernames with the role from the file.
    - Updates the role if it changed.
    - Removes DB users that no longer exist in the file (and their sessions
      cascade-delete via FK).
    """

    cursor = conn.execute("SELECT id, username, role FROM users")
    existing = {row["username"]: (row["id"], row["role"]) for row in cursor.fetchall()}

    for username, (_password, role) in file_users.items():
        if username in existing:
            _, current_role = existing[username]
            if current_role != role:
                conn.execute(
                    "UPDATE users SET role = ?, updated_at = CURRENT_TIMESTAMP WHERE username = ?",
                    (role, username),
                )
                if current_role == "user" and role == "admin":
                    # Promoted: drop any explicit page rows; admins always get everything.
                    user_id, _ = existing[username]
                    conn.execute("DELETE FROM user_pages WHERE user_id = ?", (user_id,))
        else:
            conn.execute(
                "INSERT INTO users(username, role) VALUES(?, ?)",
                (username, role),
            )

    obsolete = set(existing) - set(file_users)
    for username in obsolete:
        conn.execute("DELETE FROM users WHERE username = ?", (username,))

    conn.commit()


def login(
    conn: sqlite3.Connection,
    password_path: Path,
    username: str,
    password: str,
) -> tuple[str, CurrentUser] | None:
    """Verify credentials against ``password.txt`` and create a session.

    Returns ``(token, CurrentUser)`` on success, or ``None`` on failure.
    """

    file_users = parse_password_file(password_path)
    sync_users(conn, file_users)

    record = file_users.get(username)
    if not record:
        return None
    expected_password, _role = record
    # Constant-time comparison even though the file is plaintext locally.
    if not hmac.compare_digest(expected_password, password):
        return None

    row = conn.execute(
        "SELECT id, username, role FROM users WHERE username = ?", (username,)
    ).fetchone()
    if not row:
        return None

    token = secrets.token_urlsafe(32)
    expires_at = (datetime.now(timezone.utc) + timedelta(days=SESSION_TTL_DAYS)).isoformat()
    conn.execute(
        "INSERT INTO user_sessions(token, user_id, expires_at) VALUES(?, ?, ?)",
        (token, row["id"], expires_at),
    )
    conn.commit()

    pages = _load_pages(conn, row["id"], row["role"])
    return token, CurrentUser(
        id=row["id"], username=row["username"], role=row["role"], pages=pages
    )


def get_session(conn: sqlite3.Connection, token: str | None) -> CurrentUser | None:
    if not token:
        return None
    row = conn.execute(
        """
        SELECT u.id, u.username, u.role, s.expires_at
        FROM user_sessions s
        JOIN users u ON u.id = s.user_id
        WHERE s.token = ?
        """,
        (token,),
    ).fetchone()
    if not row:
        return None
    if row["expires_at"] < datetime.now(timezone.utc).isoformat():
        conn.execute("DELETE FROM user_sessions WHERE token = ?", (token,))
        conn.commit()
        return None
    pages = _load_pages(conn, row["id"], row["role"])
    return CurrentUser(id=row["id"], username=row["username"], role=row["role"], pages=pages)


def logout(conn: sqlite3.Connection, token: str | None) -> None:
    if not token:
        return
    conn.execute("DELETE FROM user_sessions WHERE token = ?", (token,))
    conn.commit()


def cleanup_expired_sessions(conn: sqlite3.Connection) -> int:
    cursor = conn.execute(
        "DELETE FROM user_sessions WHERE expires_at < ?",
        (datetime.now(timezone.utc).isoformat(),),
    )
    conn.commit()
    return cursor.rowcount or 0


def list_users(
    conn: sqlite3.Connection, password_path: Path
) -> list[dict[str, object]]:
    """Return all users with their page permissions, syncing the file first."""

    file_users = parse_password_file(password_path)
    sync_users(conn, file_users)
    rows = conn.execute(
        "SELECT id, username, role FROM users ORDER BY role DESC, username ASC"
    ).fetchall()
    page_rows = conn.execute("SELECT user_id, page FROM user_pages").fetchall()
    page_map: dict[int, list[str]] = {}
    for row in page_rows:
        page_map.setdefault(row["user_id"], []).append(row["page"])
    items: list[dict[str, object]] = []
    for row in rows:
        user_id, role = row["id"], row["role"]
        if role == "admin":
            pages = list(ALL_PAGES)
        else:
            pages = sorted(page_map.get(user_id, []))
        items.append(
            {
                "id": user_id,
                "username": row["username"],
                "role": role,
                "pages": pages,
            }
        )
    return items


def set_user_pages(conn: sqlite3.Connection, user_id: int, pages: Iterable[str]) -> None:
    role_row = conn.execute("SELECT role FROM users WHERE id = ?", (user_id,)).fetchone()
    if not role_row:
        raise ValueError("User not found")
    if role_row["role"] == "admin":
        raise ValueError("Admin users always have all permissions; cannot edit")
    valid_pages = {p for p in pages if p in ALL_PAGES}
    conn.execute("DELETE FROM user_pages WHERE user_id = ?", (user_id,))
    if valid_pages:
        conn.executemany(
            "INSERT INTO user_pages(user_id, page) VALUES(?, ?)",
            [(user_id, page) for page in sorted(valid_pages)],
        )
    conn.commit()


def _load_pages(conn: sqlite3.Connection, user_id: int, role: str) -> frozenset[str]:
    if role == "admin":
        return frozenset(ALL_PAGES)
    rows = conn.execute(
        "SELECT page FROM user_pages WHERE user_id = ?", (user_id,)
    ).fetchall()
    return frozenset(row["page"] for row in rows)
