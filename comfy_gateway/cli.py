from __future__ import annotations

import argparse
import os
import sys

from .config import load_settings
from .keys import create_key, list_keys, revoke_key


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="comfypress-gateway")
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("serve", help="run the authenticated API gateway")

    keys_parser = commands.add_parser("keys", help="manage gateway API keys")
    key_commands = keys_parser.add_subparsers(dest="key_command", required=True)
    create_parser = key_commands.add_parser("create", help="create a bearer key; the secret is shown once")
    create_parser.add_argument("--name", required=True, help="human-readable client label")
    key_commands.add_parser("list", help="list key labels and status, never secret material")
    revoke_parser = key_commands.add_parser("revoke", help="revoke a key by ID")
    revoke_parser.add_argument("key_id")
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    arguments = parser.parse_args(argv)
    database = os.environ.get("KEY_DB_PATH", "/data/keys.sqlite3")

    if arguments.command == "keys":
        if arguments.key_command == "create":
            try:
                record = create_key(database, arguments.name)
            except (OSError, ValueError) as error:
                parser.error(str(error))
            print(f"Key ID: {record['id']}")
            print(f"Name: {record['name']}")
            print("Copy this token now; it cannot be shown again:")
            print(record["token"])
            return 0
        if arguments.key_command == "list":
            try:
                records = list_keys(database)
            except OSError as error:
                parser.error(str(error))
            if not records:
                print("No API keys.")
                return 0
            for record in records:
                state = "revoked" if record["revoked"] else "active"
                print(f"{record['id']}\t{state}\t{record['name']}\t{record['created_at']}")
            return 0
        if arguments.key_command == "revoke":
            try:
                changed = revoke_key(database, arguments.key_id)
            except OSError as error:
                parser.error(str(error))
            if not changed:
                print("No active key found with that ID.", file=sys.stderr)
                return 1
            print(f"Revoked key {arguments.key_id}.")
            return 0

    if arguments.command == "serve":
        try:
            settings = load_settings()
        except ValueError as error:
            parser.error(str(error))
        import uvicorn
        from .app import create_app

        uvicorn.run(
            create_app(settings),
            host=os.environ.get("GATEWAY_HOST", "0.0.0.0"),
            port=int(os.environ.get("GATEWAY_PORT", "8190")),
            log_level=os.environ.get("LOG_LEVEL", "info"),
        )
        return 0

    parser.error("Unknown command")
    return 2
