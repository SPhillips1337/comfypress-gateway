import json

import httpx
from fastapi.testclient import TestClient

from comfy_gateway.app import Settings, create_app
from comfy_gateway.keys import create_key


def make_app(tmp_path, handler, *, max_body_bytes=1024):
    database = tmp_path / "keys.sqlite3"
    settings = Settings(
        upstream_url="http://comfy.test:8188",
        key_db_path=database,
        max_body_bytes=max_body_bytes,
        timeout_seconds=2.0,
    )
    app = create_app(settings, transport_factory=lambda: httpx.MockTransport(handler))
    key = create_key(database, "wordpress-site")["token"]
    return app, key


def test_missing_and_invalid_keys_are_denied_before_upstream_call(tmp_path):
    calls = []

    def upstream(request):
        calls.append(request)
        return httpx.Response(200, json={"prompt_id": "p1"})

    app, _ = make_app(tmp_path, upstream)
    with TestClient(app) as client:
        missing = client.get("/history/p1")
        invalid = client.get("/history/p1", headers={"Authorization": "Bearer not-a-key"})

    assert missing.status_code == invalid.status_code == 401
    assert missing.json() == invalid.json() == {"detail": "Invalid API key"}
    assert calls == []


def test_prompt_forwards_to_fixed_upstream_and_strips_bearer_key(tmp_path):
    captured = []

    def upstream(request):
        captured.append(request)
        return httpx.Response(200, json={"prompt_id": "p1"})

    app, key = make_app(tmp_path, upstream)
    with TestClient(app) as client:
        response = client.post(
            "/prompt",
            json={"prompt": {"1": {"inputs": {"text": "a cat"}}}},
            headers={"Authorization": f"Bearer {key}"},
        )

    assert response.status_code == 200
    assert response.json() == {"prompt_id": "p1"}
    assert len(captured) == 1
    assert captured[0].url == "http://comfy.test:8188/prompt"
    assert captured[0].headers.get("authorization") is None
    assert json.loads(captured[0].content)["prompt"]["1"]["inputs"]["text"] == "a cat"


def test_view_preserves_only_supported_query_and_streams_safe_response_headers(tmp_path):
    captured = []
    image = b"\x89PNG\r\nimage-bytes"

    def upstream(request):
        captured.append(request)
        return httpx.Response(
            200,
            content=image,
            headers={
                "content-type": "image/png",
                "content-length": str(len(image)),
                "set-cookie": "private=secret",
                "x-internal-path": "/srv/comfy",
            },
        )

    app, key = make_app(tmp_path, upstream)
    with TestClient(app) as client:
        response = client.get(
            "/view?filename=result.png&subfolder=previews%2Fdemo&type=output&ignore=1",
            headers={"Authorization": f"Bearer {key}"},
        )

    assert response.status_code == 200
    assert response.content == image
    assert response.headers["content-type"] == "image/png"
    assert "set-cookie" not in response.headers
    assert "x-internal-path" not in response.headers
    assert captured[0].url.path == "/view"
    assert dict(captured[0].url.params) == {
        "filename": "result.png",
        "subfolder": "previews/demo",
        "type": "output",
    }


def test_only_comfypress_routes_are_exposed(tmp_path):
    calls = []

    def upstream(request):
        calls.append(request)
        return httpx.Response(200, json={})

    app, key = make_app(tmp_path, upstream)
    with TestClient(app) as client:
        health = client.get("/healthz")
        denied = client.get("/system_stats", headers={"Authorization": f"Bearer {key}"})
        wrong_method = client.get("/prompt", headers={"Authorization": f"Bearer {key}"})

    assert health.status_code == 200
    assert health.json() == {"status": "ok"}
    assert denied.status_code == 404
    assert wrong_method.status_code == 405
    assert calls == []


def test_prompt_body_limit_applies_before_upstream_call(tmp_path):
    calls = []

    def upstream(request):
        calls.append(request)
        return httpx.Response(200, json={})

    app, key = make_app(tmp_path, upstream, max_body_bytes=8)
    with TestClient(app) as client:
        response = client.post(
            "/prompt",
            content=b"123456789",
            headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
        )

    assert response.status_code == 413
    assert calls == []


def test_history_rejects_invalid_prompt_id_before_upstream_call(tmp_path):
    calls = []

    def upstream(request):
        calls.append(request)
        return httpx.Response(200, json={})

    app, key = make_app(tmp_path, upstream)
    with TestClient(app) as client:
        response = client.get(
            "/history/../secret",
            headers={"Authorization": f"Bearer {key}"},
        )

    assert response.status_code in (400, 404)
    assert calls == []


def test_upstream_transport_error_is_sanitized(tmp_path):
    def upstream(request):
        raise httpx.ConnectError("private host and port", request=request)

    app, key = make_app(tmp_path, upstream)
    with TestClient(app) as client:
        response = client.get("/history/p1", headers={"Authorization": f"Bearer {key}"})

    assert response.status_code == 502
    assert response.json() == {"detail": "ComfyUI upstream unavailable"}
    assert "private host and port" not in response.text


def test_upstream_error_body_is_sanitized(tmp_path):
    def upstream(request):
        return httpx.Response(500, text="private traceback and local filesystem path")

    app, key = make_app(tmp_path, upstream)
    with TestClient(app) as client:
        response = client.get("/history/p1", headers={"Authorization": f"Bearer {key}"})

    assert response.status_code == 500
    assert response.json() == {"detail": "ComfyUI upstream request failed"}
    assert "private traceback" not in response.text
    assert "local filesystem path" not in response.text


def test_upstream_redirect_is_not_forwarded(tmp_path):
    def upstream(request):
        return httpx.Response(302, headers={"location": "http://private-comfy.local/debug"})

    app, key = make_app(tmp_path, upstream)
    with TestClient(app) as client:
        response = client.get("/history/p1", headers={"Authorization": f"Bearer {key}"})

    assert response.status_code == 502
    assert response.json() == {"detail": "ComfyUI upstream returned a redirect"}
    assert "location" not in response.headers
    assert "private-comfy.local" not in response.text
