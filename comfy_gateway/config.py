from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit


@dataclass(frozen=True)
class Settings:
    upstream_url: str
    key_db_path: Path
    max_body_bytes: int = 2 * 1024 * 1024
    timeout_seconds: float = 30.0


def validate_upstream_url(value: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError("COMFYUI_UPSTREAM must be configured")
    value = value.strip()
    parts = urlsplit(value)
    if parts.scheme not in ("http", "https") or not parts.hostname:
        raise ValueError("COMFYUI_UPSTREAM must be an HTTP(S) URL with a hostname")
    if parts.username is not None or parts.password is not None:
        raise ValueError("COMFYUI_UPSTREAM must not contain embedded credentials")
    if parts.query or parts.fragment:
        raise ValueError("COMFYUI_UPSTREAM must not contain a query or fragment")
    if any(character.isspace() for character in parts.netloc):
        raise ValueError("COMFYUI_UPSTREAM contains invalid whitespace")
    try:
        port = parts.port
    except ValueError as error:
        raise ValueError("COMFYUI_UPSTREAM has an invalid port") from error
    if port is not None and not 1 <= port <= 65535:
        raise ValueError("COMFYUI_UPSTREAM has an invalid port")
    path = parts.path.rstrip("/")
    return urlunsplit((parts.scheme, parts.netloc, path, "", ""))


def load_settings() -> Settings:
    upstream = validate_upstream_url(os.environ.get("COMFYUI_UPSTREAM", ""))
    try:
        max_body_bytes = int(os.environ.get("MAX_PROMPT_BODY_BYTES", str(2 * 1024 * 1024)))
        timeout_seconds = float(os.environ.get("UPSTREAM_TIMEOUT_SECONDS", "30"))
    except ValueError as error:
        raise ValueError("Gateway size and timeout settings must be numeric") from error
    if not 1024 <= max_body_bytes <= 16 * 1024 * 1024:
        raise ValueError("MAX_PROMPT_BODY_BYTES must be between 1024 and 16777216")
    if not 1 <= timeout_seconds <= 300:
        raise ValueError("UPSTREAM_TIMEOUT_SECONDS must be between 1 and 300")
    return Settings(
        upstream_url=upstream,
        key_db_path=Path(os.environ.get("KEY_DB_PATH", "/data/keys.sqlite3")),
        max_body_bytes=max_body_bytes,
        timeout_seconds=timeout_seconds,
    )
