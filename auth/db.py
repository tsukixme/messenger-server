"""
Хранилище сессий входа и истории запросов в SQLite.

Зачем: раньше всё хранилось в памяти процесса (dict) и терялось при
перезапуске контейнера. Здесь данные переживают перезапуск, а доступ к
sqlite3 (он синхронный) обёрнут через run_in_threadpool, чтобы не
блокировать остальные запросы FastAPI.
"""
import sqlite3
import threading
from pathlib import Path

from starlette.concurrency import run_in_threadpool

_SCHEMA = """
CREATE TABLE IF NOT EXISTS sessions (
    sid TEXT PRIMARY KEY,
    phone TEXT NOT NULL,
    code TEXT NOT NULL,
    expires_at REAL NOT NULL,
    verified INTEGER NOT NULL DEFAULT 0,
    created_at REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_sessions_code ON sessions(code);

CREATE TABLE IF NOT EXISTS start_attempts (
    phone TEXT NOT NULL,
    ts REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_start_attempts_phone ON start_attempts(phone);
"""


class Database:
    """Одно общее соединение sqlite3 плюс блокировка, чтобы потоки не мешали друг другу."""

    def __init__(self, path: str):
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        self._conn = sqlite3.connect(path, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        with self._lock:
            self._conn.executescript(_SCHEMA)
            self._conn.commit()

    # ---- синхронные реализации, выполняются в отдельном потоке ----

    def _create_session(self, sid, phone, code, expires_at, now):
        with self._lock:
            self._conn.execute(
                "INSERT INTO sessions (sid, phone, code, expires_at, verified, created_at) "
                "VALUES (?, ?, ?, ?, 0, ?)",
                (sid, phone, code, expires_at, now),
            )
            self._conn.commit()

    def _get_session(self, sid):
        with self._lock:
            row = self._conn.execute("SELECT * FROM sessions WHERE sid = ?", (sid,)).fetchone()
        return dict(row) if row else None

    def _delete_session(self, sid):
        with self._lock:
            self._conn.execute("DELETE FROM sessions WHERE sid = ?", (sid,))
            self._conn.commit()

    def _mark_verified_by_code(self, code, phone):
        """Находит неподтверждённую сессию с этим кодом.

        Возвращает: sid, если код найден и номер совпал (сессия помечена
        подтверждённой); строку "wrong_phone", если код существует, но
        принадлежит другому номеру; None, если такого кода нет вовсе.
        """
        with self._lock:
            row = self._conn.execute(
                "SELECT sid, phone FROM sessions WHERE code = ? AND verified = 0",
                (code,),
            ).fetchone()
            if not row:
                return None
            if row["phone"] != phone:
                return "wrong_phone"
            self._conn.execute("UPDATE sessions SET verified = 1 WHERE sid = ?", (row["sid"],))
            self._conn.commit()
            return row["sid"]

    def _cleanup(self, now):
        with self._lock:
            self._conn.execute("DELETE FROM sessions WHERE expires_at < ?", (now,))
            self._conn.execute("DELETE FROM start_attempts WHERE ts < ?", (now - 3600,))
            self._conn.commit()

    def _count_recent_starts(self, phone, since):
        with self._lock:
            row = self._conn.execute(
                "SELECT COUNT(*) AS c FROM start_attempts WHERE phone = ? AND ts >= ?",
                (phone, since),
            ).fetchone()
        return row["c"]

    def _record_start(self, phone, ts):
        with self._lock:
            self._conn.execute("INSERT INTO start_attempts (phone, ts) VALUES (?, ?)", (phone, ts))
            self._conn.commit()

    def _active_codes(self):
        with self._lock:
            rows = self._conn.execute("SELECT code FROM sessions WHERE verified = 0").fetchall()
        return {r["code"] for r in rows}

    def _wipe(self):
        """Только для тестов: полностью очищает обе таблицы."""
        with self._lock:
            self._conn.execute("DELETE FROM sessions")
            self._conn.execute("DELETE FROM start_attempts")
            self._conn.commit()

    # ---- асинхронные обёртки, которые вызывает app.py ----

    async def create_session(self, sid, phone, code, expires_at, now):
        await run_in_threadpool(self._create_session, sid, phone, code, expires_at, now)

    async def get_session(self, sid):
        return await run_in_threadpool(self._get_session, sid)

    async def delete_session(self, sid):
        await run_in_threadpool(self._delete_session, sid)

    async def mark_verified_by_code(self, code, phone):
        return await run_in_threadpool(self._mark_verified_by_code, code, phone)

    async def cleanup(self, now):
        await run_in_threadpool(self._cleanup, now)

    async def count_recent_starts(self, phone, since):
        return await run_in_threadpool(self._count_recent_starts, phone, since)

    async def record_start(self, phone, ts):
        await run_in_threadpool(self._record_start, phone, ts)

    async def active_codes(self):
        return await run_in_threadpool(self._active_codes)

    async def wipe(self):
        await run_in_threadpool(self._wipe)
