"""SQLite database: users, knowledge entries and their search vectors.

One file (data/campus.db) holds everything, so backing up the app is just
copying the data folder.
"""
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone

from . import config

DB_PATH = config.DATA_DIR / "campus.db"

SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    login         TEXT NOT NULL UNIQUE COLLATE NOCASE,   -- e.g. USN or staff ID
    name          TEXT NOT NULL,
    role          TEXT NOT NULL CHECK (role IN ('admin', 'student')),
    password_hash TEXT NOT NULL,
    face          BLOB,                                 -- 128-number face signature, never the photo
    created_at    TEXT NOT NULL,
    updated_at    TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS modules (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    title      TEXT NOT NULL,
    content    TEXT NOT NULL,
    source     TEXT NOT NULL DEFAULT 'manual',          -- manual | csv | file
    updated_by TEXT,
    updated_at TEXT NOT NULL
);

-- The "vector database": each entry is split into chunks and every chunk
-- stores its 384-number embedding.
CREATE TABLE IF NOT EXISTS chunks (
    id        INTEGER PRIMARY KEY AUTOINCREMENT,
    module_id INTEGER NOT NULL REFERENCES modules(id) ON DELETE CASCADE,
    position  INTEGER NOT NULL,
    text      TEXT NOT NULL,
    vector    BLOB NOT NULL
);
CREATE INDEX IF NOT EXISTS chunks_module ON chunks(module_id);
"""


def now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


@contextmanager
def connect():
    conn = sqlite3.connect(DB_PATH, timeout=10)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def init() -> None:
    with connect() as conn:
        conn.execute("PRAGMA journal_mode = WAL")
        conn.executescript(SCHEMA)


# --- Users --------------------------------------------------------------------

USER_FIELDS = "id, login, name, role, face IS NOT NULL AS has_face, created_at, updated_at"


def count_users() -> int:
    with connect() as conn:
        return conn.execute("SELECT COUNT(*) FROM users").fetchone()[0]


def create_first_admin(login: str, name: str, password_hash: str) -> int | None:
    """Create the first admin, but only while there are no users at all."""
    with connect() as conn:
        cur = conn.execute(
            "INSERT INTO users (login, name, role, password_hash, created_at, updated_at) "
            "SELECT ?, ?, 'admin', ?, ?, ? WHERE NOT EXISTS (SELECT 1 FROM users)",
            (login, name, password_hash, now(), now()),
        )
        return cur.lastrowid if cur.rowcount else None


def create_user(login: str, name: str, role: str, password_hash: str) -> dict:
    with connect() as conn:
        cur = conn.execute(
            "INSERT INTO users (login, name, role, password_hash, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?)",
            (login, name, role, password_hash, now(), now()),
        )
        user_id = cur.lastrowid
    return get_user(user_id)


def get_user(user_id: int) -> dict | None:
    with connect() as conn:
        row = conn.execute(f"SELECT {USER_FIELDS} FROM users WHERE id = ?", (user_id,)).fetchone()
    return dict(row) if row else None


def get_login(login: str) -> dict | None:
    """User row including the password hash, for signing in."""
    with connect() as conn:
        row = conn.execute("SELECT id, password_hash FROM users WHERE login = ?", (login,)).fetchone()
    return dict(row) if row else None


def list_users() -> list[dict]:
    with connect() as conn:
        rows = conn.execute(f"SELECT {USER_FIELDS} FROM users ORDER BY role, login").fetchall()
    return [dict(r) for r in rows]


def update_user(user_id: int, name: str, role: str) -> bool:
    with connect() as conn:
        cur = conn.execute(
            "UPDATE users SET name = ?, role = ?, updated_at = ? WHERE id = ?", (name, role, now(), user_id)
        )
    return cur.rowcount > 0


def set_password(user_id: int, password_hash: str) -> bool:
    with connect() as conn:
        cur = conn.execute(
            "UPDATE users SET password_hash = ?, updated_at = ? WHERE id = ?", (password_hash, now(), user_id)
        )
    return cur.rowcount > 0


def delete_user(user_id: int) -> bool:
    with connect() as conn:
        cur = conn.execute("DELETE FROM users WHERE id = ?", (user_id,))
    return cur.rowcount > 0


def count_admins() -> int:
    with connect() as conn:
        return conn.execute("SELECT COUNT(*) FROM users WHERE role = 'admin'").fetchone()[0]


def get_face(user_id: int) -> bytes | None:
    with connect() as conn:
        row = conn.execute("SELECT face FROM users WHERE id = ?", (user_id,)).fetchone()
    return row["face"] if row else None


def set_face(user_id: int, face: bytes | None) -> bool:
    with connect() as conn:
        cur = conn.execute("UPDATE users SET face = ?, updated_at = ? WHERE id = ?", (face, now(), user_id))
    return cur.rowcount > 0


# --- Knowledge entries -----------------------------------------------------------

def list_modules() -> list[dict]:
    with connect() as conn:
        rows = conn.execute("SELECT * FROM modules ORDER BY updated_at DESC, id DESC").fetchall()
    return [dict(r) for r in rows]


def get_module(module_id: int) -> dict | None:
    with connect() as conn:
        row = conn.execute("SELECT * FROM modules WHERE id = ?", (module_id,)).fetchone()
    return dict(row) if row else None


def create_module(title: str, content: str, source: str, user: str) -> dict:
    with connect() as conn:
        cur = conn.execute(
            "INSERT INTO modules (title, content, source, updated_by, updated_at) VALUES (?, ?, ?, ?, ?)",
            (title, content, source, user, now()),
        )
        module_id = cur.lastrowid
    return get_module(module_id)


def update_module(module_id: int, title: str, content: str, user: str) -> dict | None:
    with connect() as conn:
        cur = conn.execute(
            "UPDATE modules SET title = ?, content = ?, updated_by = ?, updated_at = ? WHERE id = ?",
            (title, content, user, now(), module_id),
        )
        if cur.rowcount == 0:
            return None
    return get_module(module_id)


def delete_module(module_id: int) -> bool:
    with connect() as conn:
        cur = conn.execute("DELETE FROM modules WHERE id = ?", (module_id,))
    return cur.rowcount > 0


def replace_chunks(module_id: int, rows: list[tuple[int, str, bytes]]) -> None:
    with connect() as conn:
        conn.execute("DELETE FROM chunks WHERE module_id = ?", (module_id,))
        conn.executemany(
            "INSERT INTO chunks (module_id, position, text, vector) VALUES (?, ?, ?, ?)",
            [(module_id, pos, text, vec) for pos, text, vec in rows],
        )


def all_chunks() -> list[dict]:
    with connect() as conn:
        rows = conn.execute(
            "SELECT c.id, c.module_id, c.position, c.text, c.vector, m.title "
            "FROM chunks c JOIN modules m ON m.id = c.module_id ORDER BY c.id"
        ).fetchall()
    return [dict(r) for r in rows]
