from __future__ import annotations

import hashlib
import secrets
import sqlite3
import uuid
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator


def _connect(database: Path) -> sqlite3.Connection:
    database = Path(database)
    database.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(database, timeout=15)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA journal_mode=WAL")
    connection.execute("PRAGMA busy_timeout=15000")
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS api_keys (
            id TEXT PRIMARY KEY,
            name TEXT NOT NULL,
            token_hash TEXT NOT NULL UNIQUE,
            created_at TEXT NOT NULL,
            revoked_at TEXT
        )
        """
    )
    connection.execute("CREATE INDEX IF NOT EXISTS api_keys_token_hash ON api_keys(token_hash)")
    connection.commit()
    return connection


@contextmanager
def _connection(database: Path) -> Iterator[sqlite3.Connection]:
    connection = _connect(database)
    try:
        yield connection
        connection.commit()
    except Exception:
        connection.rollback()
        raise
    finally:
        connection.close()


def create_key(database: Path, name: str) -> dict[str, str]:
    normalized_name = name.strip()
    if not normalized_name or len(normalized_name) > 80:
        raise ValueError("Key name must contain 1 to 80 characters")

    token = "cpwg_" + secrets.token_urlsafe(32)
    token_hash = hashlib.sha256(token.encode("utf-8")).hexdigest()
    record_id = uuid.uuid4().hex[:16]
    created_at = datetime.now(timezone.utc).isoformat(timespec="seconds")
    with _connection(Path(database)) as connection:
        connection.execute(
            "INSERT INTO api_keys (id, name, token_hash, created_at) VALUES (?, ?, ?, ?)",
            (record_id, normalized_name, token_hash, created_at),
        )
    return {"id": record_id, "name": normalized_name, "created_at": created_at, "token": token}


def validate_token(database: Path, token: str) -> bool:
    if not isinstance(token, str) or not token.startswith("cpwg_") or len(token) > 160:
        return False
    token_hash = hashlib.sha256(token.encode("utf-8")).hexdigest()
    with _connection(Path(database)) as connection:
        row = connection.execute(
            "SELECT 1 FROM api_keys WHERE token_hash = ? AND revoked_at IS NULL LIMIT 1",
            (token_hash,),
        ).fetchone()
    return row is not None


def list_keys(database: Path) -> list[dict[str, Any]]:
    with _connection(Path(database)) as connection:
        rows = connection.execute(
            "SELECT id, name, created_at, revoked_at FROM api_keys ORDER BY created_at, id"
        ).fetchall()
    return [
        {
            "id": row["id"],
            "name": row["name"],
            "created_at": row["created_at"],
            "revoked": row["revoked_at"] is not None,
        }
        for row in rows
    ]


def revoke_key(database: Path, record_id: str) -> bool:
    revoked_at = datetime.now(timezone.utc).isoformat(timespec="seconds")
    with _connection(Path(database)) as connection:
        cursor = connection.execute(
            "UPDATE api_keys SET revoked_at = ? WHERE id = ? AND revoked_at IS NULL",
            (revoked_at, record_id),
        )
        return cursor.rowcount == 1
