from __future__ import annotations

import json
import secrets
import sqlite3
from datetime import datetime, timedelta, timezone
from http import HTTPStatus
from http.cookies import SimpleCookie
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse
from hashlib import pbkdf2_hmac


BASE_DIR = Path(__file__).resolve().parent
PUBLIC_DIR = BASE_DIR / "public"
DB_PATH = BASE_DIR / "blog.db"
SESSION_DAYS = 7


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def hash_password(password: str, salt: str | None = None) -> str:
    salt = salt or secrets.token_hex(16)
    digest = pbkdf2_hmac("sha256", password.encode(), salt.encode(), 120_000)
    return f"{salt}${digest.hex()}"


def verify_password(password: str, stored_hash: str) -> bool:
    try:
        salt, digest = stored_hash.split("$", 1)
    except ValueError:
        return False
    return secrets.compare_digest(hash_password(password, salt), f"{salt}${digest}")


def connect() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def init_db() -> None:
    with connect() as conn:
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS users (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                username TEXT NOT NULL UNIQUE,
                password_hash TEXT NOT NULL,
                created_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS sessions (
                token TEXT PRIMARY KEY,
                user_id INTEGER NOT NULL,
                expires_at TEXT NOT NULL,
                FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
            );

            CREATE TABLE IF NOT EXISTS posts (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                title TEXT NOT NULL,
                content TEXT NOT NULL,
                author_id INTEGER NOT NULL,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                FOREIGN KEY (author_id) REFERENCES users(id) ON DELETE CASCADE
            );

            CREATE TABLE IF NOT EXISTS comments (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                body TEXT NOT NULL,
                post_id INTEGER NOT NULL,
                author_id INTEGER NOT NULL,
                created_at TEXT NOT NULL,
                FOREIGN KEY (post_id) REFERENCES posts(id) ON DELETE CASCADE,
                FOREIGN KEY (author_id) REFERENCES users(id) ON DELETE CASCADE
            );
            """
        )


def row_to_dict(row: sqlite3.Row) -> dict:
    return {key: row[key] for key in row.keys()}


class BlogHandler(SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=str(PUBLIC_DIR), **kwargs)

    def log_message(self, format: str, *args) -> None:
        print(f"{self.address_string()} - {format % args}")

    def send_json(self, status: HTTPStatus, payload: dict | list, headers: dict | None = None) -> None:
        encoded = json.dumps(payload).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(encoded)))
        for key, value in (headers or {}).items():
            self.send_header(key, value)
        self.end_headers()
        self.wfile.write(encoded)

    def read_json(self) -> dict:
        length = int(self.headers.get("Content-Length", "0"))
        if length == 0:
            return {}
        try:
            return json.loads(self.rfile.read(length))
        except json.JSONDecodeError:
            self.send_json(HTTPStatus.BAD_REQUEST, {"error": "Invalid JSON body"})
            raise

    def current_user(self) -> sqlite3.Row | None:
        cookie_header = self.headers.get("Cookie", "")
        cookie = SimpleCookie(cookie_header)
        token = cookie.get("session")
        if token is None:
            return None
        now = utc_now()
        with connect() as conn:
            return conn.execute(
                """
                SELECT users.id, users.username
                FROM sessions
                JOIN users ON users.id = sessions.user_id
                WHERE sessions.token = ? AND sessions.expires_at > ?
                """,
                (token.value, now),
            ).fetchone()

    def require_user(self) -> sqlite3.Row | None:
        user = self.current_user()
        if user is None:
            self.send_json(HTTPStatus.UNAUTHORIZED, {"error": "Authentication required"})
        return user

    def route_parts(self) -> tuple[str, list[str], dict[str, list[str]]]:
        parsed = urlparse(self.path)
        parts = [part for part in parsed.path.split("/") if part]
        return parsed.path, parts, parse_qs(parsed.query)

    def do_GET(self) -> None:
        _, parts, _ = self.route_parts()
        if not parts or parts[0] != "api":
            return super().do_GET()
        if parts == ["api", "me"]:
            return self.get_me()
        if parts == ["api", "posts"]:
            return self.list_posts()
        if len(parts) == 3 and parts[:2] == ["api", "posts"]:
            return self.get_post(int(parts[2]))
        self.send_json(HTTPStatus.NOT_FOUND, {"error": "Route not found"})

    def do_POST(self) -> None:
        _, parts, _ = self.route_parts()
        if parts == ["api", "register"]:
            return self.register()
        if parts == ["api", "login"]:
            return self.login()
        if parts == ["api", "logout"]:
            return self.logout()
        if parts == ["api", "posts"]:
            return self.create_post()
        if len(parts) == 4 and parts[:2] == ["api", "posts"] and parts[3] == "comments":
            return self.create_comment(int(parts[2]))
        self.send_json(HTTPStatus.NOT_FOUND, {"error": "Route not found"})

    def do_PUT(self) -> None:
        _, parts, _ = self.route_parts()
        if len(parts) == 3 and parts[:2] == ["api", "posts"]:
            return self.update_post(int(parts[2]))
        self.send_json(HTTPStatus.NOT_FOUND, {"error": "Route not found"})

    def do_DELETE(self) -> None:
        _, parts, _ = self.route_parts()
        if len(parts) == 3 and parts[:2] == ["api", "posts"]:
            return self.delete_post(int(parts[2]))
        self.send_json(HTTPStatus.NOT_FOUND, {"error": "Route not found"})

    def get_me(self) -> None:
        user = self.current_user()
        self.send_json(HTTPStatus.OK, {"user": row_to_dict(user) if user else None})

    def register(self) -> None:
        data = self.read_json()
        username = data.get("username", "").strip()
        password = data.get("password", "")
        if len(username) < 3 or len(password) < 6:
            return self.send_json(
                HTTPStatus.BAD_REQUEST,
                {"error": "Username must be at least 3 characters and password at least 6 characters"},
            )
        try:
            with connect() as conn:
                conn.execute(
                    "INSERT INTO users (username, password_hash, created_at) VALUES (?, ?, ?)",
                    (username, hash_password(password), utc_now()),
                )
        except sqlite3.IntegrityError:
            return self.send_json(HTTPStatus.CONFLICT, {"error": "Username already exists"})
        return self.create_session_response(username, password)

    def login(self) -> None:
        data = self.read_json()
        return self.create_session_response(data.get("username", "").strip(), data.get("password", ""))

    def create_session_response(self, username: str, password: str) -> None:
        with connect() as conn:
            user = conn.execute("SELECT * FROM users WHERE username = ?", (username,)).fetchone()
            if user is None or not verify_password(password, user["password_hash"]):
                return self.send_json(HTTPStatus.UNAUTHORIZED, {"error": "Invalid username or password"})
            token = secrets.token_urlsafe(32)
            expires = datetime.now(timezone.utc) + timedelta(days=SESSION_DAYS)
            conn.execute(
                "INSERT INTO sessions (token, user_id, expires_at) VALUES (?, ?, ?)",
                (token, user["id"], expires.isoformat(timespec="seconds")),
            )
        headers = {
            "Set-Cookie": f"session={token}; HttpOnly; SameSite=Lax; Path=/; Max-Age={SESSION_DAYS * 86400}"
        }
        self.send_json(HTTPStatus.OK, {"user": {"id": user["id"], "username": user["username"]}}, headers)

    def logout(self) -> None:
        cookie = SimpleCookie(self.headers.get("Cookie", ""))
        token = cookie.get("session")
        if token:
            with connect() as conn:
                conn.execute("DELETE FROM sessions WHERE token = ?", (token.value,))
        self.send_json(
            HTTPStatus.OK,
            {"ok": True},
            {"Set-Cookie": "session=; HttpOnly; SameSite=Lax; Path=/; Max-Age=0"},
        )

    def list_posts(self) -> None:
        with connect() as conn:
            posts = conn.execute(
                """
                SELECT posts.*, users.username AS author,
                    COUNT(comments.id) AS comment_count
                FROM posts
                JOIN users ON users.id = posts.author_id
                LEFT JOIN comments ON comments.post_id = posts.id
                GROUP BY posts.id
                ORDER BY posts.created_at DESC
                """
            ).fetchall()
        self.send_json(HTTPStatus.OK, [row_to_dict(post) for post in posts])

    def get_post(self, post_id: int) -> None:
        with connect() as conn:
            post = conn.execute(
                """
                SELECT posts.*, users.username AS author
                FROM posts
                JOIN users ON users.id = posts.author_id
                WHERE posts.id = ?
                """,
                (post_id,),
            ).fetchone()
            if post is None:
                return self.send_json(HTTPStatus.NOT_FOUND, {"error": "Post not found"})
            comments = conn.execute(
                """
                SELECT comments.*, users.username AS author
                FROM comments
                JOIN users ON users.id = comments.author_id
                WHERE post_id = ?
                ORDER BY comments.created_at ASC
                """,
                (post_id,),
            ).fetchall()
        payload = row_to_dict(post)
        payload["comments"] = [row_to_dict(comment) for comment in comments]
        self.send_json(HTTPStatus.OK, payload)

    def create_post(self) -> None:
        user = self.require_user()
        if user is None:
            return
        data = self.read_json()
        title = data.get("title", "").strip()
        content = data.get("content", "").strip()
        if not title or not content:
            return self.send_json(HTTPStatus.BAD_REQUEST, {"error": "Title and content are required"})
        now = utc_now()
        with connect() as conn:
            cursor = conn.execute(
                "INSERT INTO posts (title, content, author_id, created_at, updated_at) VALUES (?, ?, ?, ?, ?)",
                (title, content, user["id"], now, now),
            )
        self.send_json(HTTPStatus.CREATED, {"id": cursor.lastrowid})

    def update_post(self, post_id: int) -> None:
        user = self.require_user()
        if user is None:
            return
        data = self.read_json()
        title = data.get("title", "").strip()
        content = data.get("content", "").strip()
        if not title or not content:
            return self.send_json(HTTPStatus.BAD_REQUEST, {"error": "Title and content are required"})
        with connect() as conn:
            post = conn.execute("SELECT author_id FROM posts WHERE id = ?", (post_id,)).fetchone()
            if post is None:
                return self.send_json(HTTPStatus.NOT_FOUND, {"error": "Post not found"})
            if post["author_id"] != user["id"]:
                return self.send_json(HTTPStatus.FORBIDDEN, {"error": "You can only edit your own posts"})
            conn.execute(
                "UPDATE posts SET title = ?, content = ?, updated_at = ? WHERE id = ?",
                (title, content, utc_now(), post_id),
            )
        self.send_json(HTTPStatus.OK, {"ok": True})

    def delete_post(self, post_id: int) -> None:
        user = self.require_user()
        if user is None:
            return
        with connect() as conn:
            post = conn.execute("SELECT author_id FROM posts WHERE id = ?", (post_id,)).fetchone()
            if post is None:
                return self.send_json(HTTPStatus.NOT_FOUND, {"error": "Post not found"})
            if post["author_id"] != user["id"]:
                return self.send_json(HTTPStatus.FORBIDDEN, {"error": "You can only delete your own posts"})
            conn.execute("DELETE FROM posts WHERE id = ?", (post_id,))
        self.send_json(HTTPStatus.OK, {"ok": True})

    def create_comment(self, post_id: int) -> None:
        user = self.require_user()
        if user is None:
            return
        body = self.read_json().get("body", "").strip()
        if not body:
            return self.send_json(HTTPStatus.BAD_REQUEST, {"error": "Comment cannot be empty"})
        with connect() as conn:
            post = conn.execute("SELECT id FROM posts WHERE id = ?", (post_id,)).fetchone()
            if post is None:
                return self.send_json(HTTPStatus.NOT_FOUND, {"error": "Post not found"})
            conn.execute(
                "INSERT INTO comments (body, post_id, author_id, created_at) VALUES (?, ?, ?, ?)",
                (body, post_id, user["id"], utc_now()),
            )
        self.send_json(HTTPStatus.CREATED, {"ok": True})


def main() -> None:
    init_db()
    server = ThreadingHTTPServer(("localhost", 8000), BlogHandler)
    print("Blog platform running at http://localhost:8000")
    server.serve_forever()


if __name__ == "__main__":
    main()
