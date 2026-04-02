"""Async SQLite session repository.

Stores server-side sessions with Fernet-encrypted Jellyfin tokens.
Uses aiosqlite in WAL mode for concurrent read access.
"""

from __future__ import annotations

import time
from typing import Any

import aiosqlite

from app.auth.crypto import fernet_decrypt, fernet_encrypt
from app.auth.models import SessionMeta, SessionRow

_CREATE_TABLE = """
CREATE TABLE IF NOT EXISTS sessions (
    session_id   TEXT PRIMARY KEY,
    user_id      TEXT NOT NULL,
    username     TEXT NOT NULL,
    server_name  TEXT NOT NULL,
    token_enc    BLOB NOT NULL,
    csrf_token   TEXT NOT NULL,
    created_at   INTEGER NOT NULL,
    expires_at   INTEGER NOT NULL
)
"""

_CREATE_INDEX_USER = """
CREATE INDEX IF NOT EXISTS idx_sessions_user_id
ON sessions(user_id, created_at)
"""

_CREATE_INDEX_EXPIRES = """
CREATE INDEX IF NOT EXISTS idx_sessions_expires_at
ON sessions(expires_at)
"""


class SessionStore:
    """Async session repository backed by SQLite."""

    def __init__(self, db_path: str, column_key: bytes) -> None:
        self._db_path = db_path
        self._column_key = column_key
        self._db: aiosqlite.Connection | None = None

    def _row_to_session(
        self,
        row: Any,
    ) -> SessionRow:
        """Build a SessionRow from a full DB row, decrypting the token."""
        return SessionRow(
            session_id=row[0],
            user_id=row[1],
            username=row[2],
            server_name=row[3],
            token=fernet_decrypt(self._column_key, row[4]),
            csrf_token=row[5],
            created_at=row[6],
            expires_at=row[7],
        )

    async def init(self) -> None:
        """Open the database connection and create the schema."""
        self._db = await aiosqlite.connect(self._db_path)
        await self._db.execute("PRAGMA journal_mode=WAL")
        await self._db.execute(_CREATE_TABLE)
        await self._db.execute(_CREATE_INDEX_USER)
        await self._db.execute(_CREATE_INDEX_EXPIRES)
        await self._db.commit()

    async def close(self) -> None:
        """Close the database connection."""
        if self._db:
            await self._db.close()
            self._db = None

    @property
    def _conn(self) -> aiosqlite.Connection:
        if self._db is None:
            msg = "SessionStore not initialised — call init() first"
            raise RuntimeError(msg)
        return self._db

    async def create(
        self,
        *,
        session_id: str,
        user_id: str,
        username: str,
        server_name: str,
        token: str,
        csrf_token: str,
        expires_at: int,
    ) -> None:
        """Insert a new session, encrypting the token at rest."""
        token_enc = fernet_encrypt(self._column_key, token)
        created_at = int(time.time())
        await self._conn.execute(
            """INSERT INTO sessions
               (session_id, user_id, username, server_name, token_enc,
                csrf_token, created_at, expires_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                session_id,
                user_id,
                username,
                server_name,
                token_enc,
                csrf_token,
                created_at,
                expires_at,
            ),
        )
        await self._conn.commit()

    async def get(self, session_id: str) -> SessionRow | None:
        """Fetch a session by ID, decrypting the token."""
        cursor = await self._conn.execute(
            """SELECT session_id, user_id, username, server_name, token_enc,
                      csrf_token, created_at, expires_at
               FROM sessions WHERE session_id = ?""",
            (session_id,),
        )
        row = await cursor.fetchone()
        if row is None:
            return None
        return self._row_to_session(row)

    async def get_metadata(self, session_id: str) -> SessionMeta | None:
        """Fetch session metadata WITHOUT decrypting the token."""
        cursor = await self._conn.execute(
            """SELECT session_id, user_id, username, server_name, expires_at
               FROM sessions WHERE session_id = ?""",
            (session_id,),
        )
        row = await cursor.fetchone()
        if row is None:
            return None
        return SessionMeta(
            session_id=row[0],
            user_id=row[1],
            username=row[2],
            server_name=row[3],
            expires_at=row[4],
        )

    async def get_token(self, session_id: str) -> str | None:
        """Return the decrypted Jellyfin token for a session, or None.

        Returns ``None`` if the session does not exist or has expired.
        Unlike ``get()``, this never constructs a full ``SessionRow`` —
        only the encrypted token and expiry are fetched.
        """
        now = int(time.time())
        cursor = await self._conn.execute(
            "SELECT token_enc, expires_at FROM sessions WHERE session_id = ?",
            (session_id,),
        )
        row = await cursor.fetchone()
        if row is None:
            return None
        token_enc, expires_at = row
        if expires_at < now:
            return None
        return fernet_decrypt(self._column_key, token_enc)

    async def delete(self, session_id: str) -> None:
        """Delete a session by ID."""
        await self._conn.execute(
            "DELETE FROM sessions WHERE session_id = ?", (session_id,)
        )
        await self._conn.commit()

    async def get_expired(self) -> list[SessionRow]:
        """Return all sessions with expires_at in the past."""
        now = int(time.time())
        cursor = await self._conn.execute(
            """SELECT session_id, user_id, username, server_name, token_enc,
                      csrf_token, created_at, expires_at
               FROM sessions WHERE expires_at < ?""",
            (now,),
        )
        rows = await cursor.fetchall()
        return [self._row_to_session(r) for r in rows]

    async def count_by_user(self, user_id: str) -> int:
        """Count active (non-expired) sessions for a user."""
        cursor = await self._conn.execute(
            "SELECT COUNT(*) FROM sessions WHERE user_id = ? AND expires_at >= ?",
            (user_id, int(time.time())),
        )
        row = await cursor.fetchone()
        return row[0] if row else 0

    async def oldest_by_user(self, user_id: str) -> SessionRow | None:
        """Return the oldest session for a user (earliest created_at)."""
        cursor = await self._conn.execute(
            """SELECT session_id, user_id, username, server_name, token_enc,
                      csrf_token, created_at, expires_at
               FROM sessions WHERE user_id = ?
               ORDER BY created_at ASC, session_id ASC LIMIT 1""",
            (user_id,),
        )
        row = await cursor.fetchone()
        if row is None:
            return None
        return self._row_to_session(row)

    async def delete_all_by_user(self, user_id: str) -> int:
        """Delete all sessions for a user. Returns count of deleted rows."""
        cursor = await self._conn.execute(
            "DELETE FROM sessions WHERE user_id = ?", (user_id,)
        )
        await self._conn.commit()
        return cursor.rowcount
