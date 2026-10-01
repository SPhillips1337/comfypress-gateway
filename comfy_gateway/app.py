from __future__ import annotations

import re
import sqlite3
from collections.abc import Callable

import httpx
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, StreamingResponse

from .config import Settings, load_settings
from .keys import validate_token


SAFE_RESPONSE_HEADERS = {"cache-control", "content-length", "content-type", "etag", "last-modified"}


def create_app(
    settings: Settings | None = None,
    transport_factory: Callable[[], httpx.AsyncBaseTransport] | None = None,
) -> FastAPI:
    configuration = settings or load_settings()
    application = FastAPI(docs_url=None, redoc_url=None, openapi_url=None)
    application.state.settings = configuration
    application.state.transport_factory = transport_factory

    async def authorized(request: Request) -> bool:
        value = request.headers.get("authorization", "")
        scheme, separator, token = value.partition(" ")
        if not separator or scheme.lower() != "bearer" or not token or token.strip() != token:
            return False
        try:
            return validate_token(configuration.key_db_path, token)
        except sqlite3.Error:
            return False

    async def read_prompt_body(request: Request) -> bytes | JSONResponse:
        content_length = request.headers.get("content-length")
        if content_length:
            try:
                if int(content_length) > configuration.max_body_bytes:
                    return JSONResponse({"detail": "Workflow body exceeds the configured limit"}, status_code=413)
            except ValueError:
                return JSONResponse({"detail": "Invalid Content-Length"}, status_code=400)

        body = bytearray()
        async for chunk in request.stream():
            body.extend(chunk)
            if len(body) > configuration.max_body_bytes:
                return JSONResponse({"detail": "Workflow body exceeds the configured limit"}, status_code=413)
        return bytes(body)

    async def proxy(
        request: Request,
        path: str,
        query: list[tuple[str, str]] | None = None,
    ) -> StreamingResponse | JSONResponse:
        forwarded_headers = {"accept-encoding": "identity"}
        for header in ("accept", "content-type"):
            value = request.headers.get(header)
            if value:
                forwarded_headers[header] = value

        body: bytes | None = None
        if request.method == "POST":
            result = await read_prompt_body(request)
            if isinstance(result, JSONResponse):
                return result
            body = result

        upstream_url = configuration.upstream_url + path
        transport = application.state.transport_factory() if application.state.transport_factory else None
        client = httpx.AsyncClient(
            follow_redirects=False,
            timeout=configuration.timeout_seconds,
            transport=transport,
        )
        try:
            upstream_request = client.build_request(
                request.method,
                upstream_url,
                params=query,
                headers=forwarded_headers,
                content=body,
            )
            upstream_response = await client.send(upstream_request, stream=True)
        except httpx.HTTPError:
            await client.aclose()
            return JSONResponse({"detail": "ComfyUI upstream unavailable"}, status_code=502)

        if upstream_response.status_code >= 400:
            status_code = upstream_response.status_code
            await upstream_response.aclose()
            await client.aclose()
            return JSONResponse(
                {"detail": "ComfyUI upstream request failed"},
                status_code=status_code,
            )
        if 300 <= upstream_response.status_code < 400:
            await upstream_response.aclose()
            await client.aclose()
            return JSONResponse(
                {"detail": "ComfyUI upstream returned a redirect"},
                status_code=502,
            )

        response_headers = {
            key: value
            for key, value in upstream_response.headers.items()
            if key.lower() in SAFE_RESPONSE_HEADERS
        }

        async def response_stream():
            try:
                # Mock transports can return an already-buffered response; real HTTP responses stream.
                if upstream_response.is_stream_consumed:
                    if upstream_response.content:
                        yield upstream_response.content
                else:
                    async for chunk in upstream_response.aiter_raw():
                        yield chunk
            finally:
                await upstream_response.aclose()
                await client.aclose()

        return StreamingResponse(
            response_stream(),
            status_code=upstream_response.status_code,
            headers=response_headers,
        )

    @application.get("/healthz")
    async def health() -> dict[str, str]:
        return {"status": "ok"}

    @application.post("/prompt")
    async def submit_prompt(request: Request):
        if not await authorized(request):
            return JSONResponse(
                {"detail": "Invalid API key"},
                status_code=401,
                headers={"WWW-Authenticate": "Bearer"},
            )
        return await proxy(request, "/prompt")

    @application.get("/history/{prompt_id}")
    async def history(prompt_id: str, request: Request):
        if not await authorized(request):
            return JSONResponse(
                {"detail": "Invalid API key"},
                status_code=401,
                headers={"WWW-Authenticate": "Bearer"},
            )
        if not re.fullmatch(r"[A-Za-z0-9_-]{1,255}", prompt_id):
            return JSONResponse({"detail": "Invalid prompt ID"}, status_code=400)
        return await proxy(request, "/history/" + prompt_id)

    @application.get("/view")
    async def view(request: Request):
        if not await authorized(request):
            return JSONResponse(
                {"detail": "Invalid API key"},
                status_code=401,
                headers={"WWW-Authenticate": "Bearer"},
            )
        filename = request.query_params.get("filename", "")
        subfolder = request.query_params.get("subfolder", "")
        image_type = request.query_params.get("type", "output")
        if (
            not filename
            or len(filename) > 255
            or "/" in filename
            or "\\" in filename
            or any(ord(character) < 32 or ord(character) == 127 for character in filename)
        ):
            return JSONResponse({"detail": "Invalid image filename"}, status_code=400)
        if image_type not in {"output", "input", "temp"}:
            return JSONResponse({"detail": "Invalid image type"}, status_code=400)
        if (
            len(subfolder) > 512
            or "\\" in subfolder
            or any(ord(character) < 32 or ord(character) == 127 for character in subfolder)
        ):
            return JSONResponse({"detail": "Invalid image subfolder"}, status_code=400)
        if subfolder and any(segment in {"", ".", ".."} for segment in subfolder.split("/")):
            return JSONResponse({"detail": "Invalid image subfolder"}, status_code=400)
        query = [("filename", filename), ("type", image_type)]
        if subfolder:
            query.append(("subfolder", subfolder))
        return await proxy(request, "/view", query)

    return application
