import hashlib
import sqlite3

from comfy_gateway.keys import create_key, list_keys, revoke_key, validate_token


def test_create_key_stores_only_a_hash_and_list_never_returns_secret(tmp_path):
    database = tmp_path / "keys.sqlite3"

    record = create_key(database, "wordpress-site")

    assert record["token"].startswith("cpwg_")
    assert validate_token(database, record["token"])
    assert record["id"]
    assert record["name"] == "wordpress-site"
    listed = list_keys(database)
    assert len(listed) == 1
    assert listed[0]["id"] == record["id"]
    assert "token" not in listed[0]
    assert "token_hash" not in listed[0]

    with sqlite3.connect(database) as connection:
        stored_hash = connection.execute(
            "SELECT token_hash FROM api_keys WHERE id = ?", (record["id"],)
        ).fetchone()[0]

    assert stored_hash == hashlib.sha256(record["token"].encode()).hexdigest()
    assert record["token"] not in stored_hash


def test_revoked_key_is_rejected_and_revoke_is_idempotently_false(tmp_path):
    database = tmp_path / "keys.sqlite3"
    record = create_key(database, "wordpress-site")

    assert revoke_key(database, record["id"])
    assert not validate_token(database, record["token"])
    assert not revoke_key(database, record["id"])
    assert list_keys(database)[0]["revoked"] is True
