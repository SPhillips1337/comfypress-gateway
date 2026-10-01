# ComfyPress Gateway MVP Implementation Plan

> **For Hermes:** Implement the tasks in order, preserving the existing ComfyPress checkout and verifying each boundary before publishing.

**Goal:** Provide a small Compose-deployed API gateway that authenticates ComfyPress-to-ComfyUI requests with revocable bearer keys while leaving ComfyUI running wherever the operator already runs it.

**Architecture:** A FastAPI service proxies only the ComfyUI HTTP endpoints used by the plugin (`POST /prompt`, `GET /history/{prompt_id}`, and `GET /view`). It stores SHA-256 digests of randomly generated tokens in a persistent SQLite database; keys are created/revoked only through an in-container CLI, never an HTTP admin route. Docker Compose exposes only the gateway, defaults its host binding to loopback, and reaches a host-run ComfyUI through `host.docker.internal`.

**Tech Stack:** Python 3.12, FastAPI, HTTPX, Uvicorn, SQLite, pytest, Docker Compose.

---

## Product and security boundaries

- This first version is a ComfyPress-focused API gateway, not a browser UI proxy or a general ComfyUI API gateway.
- Every proxied route requires a valid API key in its authorization header. `/healthz` is the only unauthenticated route and returns no upstream information.
- Key material is generated with a cryptographic RNG, shown only once, and never stored in plaintext or logged. Docker/host administrators can manage keys through CLI commands.
- The gateway strips the bearer header before proxying. It does not add authentication to ComfyUI itself; network isolation must prevent bypassing the gateway.
- The WordPress plugin must attach the key server-side to submit, history, and image-import requests; it must never localize the secret to editor JavaScript or return it in REST responses.
- Cloudflare Tunnel is transport/reachability, not the authentication mechanism. The WordPress server sends the gateway bearer key over the tunnel's public HTTPS hostname.
- No commits or pushes to the existing ComfyPress repository. Its current dirty state is preserved; only the requested narrow source/docs changes are made there.

## Task 1: Scaffold gateway and verified configuration

Create `README.md`, `.gitignore`, `.dockerignore`, `.env.example`, pinned requirements, `Dockerfile`, `compose.yaml`, and the `comfy_gateway/` package. Validate `COMFYUI_UPSTREAM` at startup (HTTP(S), hostname, no embedded credentials/query/fragment) and fail closed on missing/invalid configuration.

## Task 2: Key lifecycle and gateway auth

Create `comfy_gateway/keys.py` and `comfy_gateway/cli.py`. Implement SQLite schema/init, `keys create --name`, `keys list`, and `keys revoke <id>`. Generate high-entropy URL-safe tokens, store only SHA-256 hashes, print the secret once, and never print it in list output. Validate bearer tokens against active keys; reject missing, malformed, revoked, and unknown tokens with the same 401 response.

## Task 3: Scoped HTTP proxy

Create `comfy_gateway/app.py` with `/healthz`, `POST /prompt`, `GET /history/{prompt_id}`, and `GET /view`. Authenticate before upstream I/O, pass only the configured origin plus the allowed path/query, strip credentials and hop-by-hop headers, enforce a bounded request body, use finite upstream timeouts, stream image responses, and return bounded sanitized errors. Return 404 for every other path. Keep logs metadata-only; do not log tokens, workflow bodies, prompts, or image contents.

## Task 4: Compose deployment and integration tests

Create tests for token create/list/revoke, hashed-at-rest behavior, authentication failures, allowlisted route/method behavior, upstream forwarding, token stripping, query preservation, streaming/content headers, upstream errors, and request-size bounds. Use a mocked HTTPX transport for deterministic upstream tests. Run pytest and `docker compose config`; build and run the stack when Docker/network access permits.

## Task 5: ComfyPress token configuration and forwarding

In the existing ComfyPress working tree, add an administrator-only password field for a gateway token; blank saves preserve the current secret, explicit clear is supported, and an optional `COMFY_IMAGE_GATEWAY_API_TOKEN` constant takes precedence. Add one helper for upstream headers and apply it to submit, history, and image-fetch requests. Keep the token out of editor localization and REST responses. Extend the PHP contract harness to assert token headers on all three calls, omission when unset, and safe sanitization. Preserve all pre-existing unrelated modifications/untracked files.

## Task 6: Setup documentation

Document the host-run Stability Matrix case, Linux `host-gateway` behavior, key creation/revocation, WordPress base URL/token setup, Cloudflare named Tunnel hostname targeting the gateway rather than ComfyUI, HTTPS expectation, direct-port bypass warning, and the fact that the project does not expose the ComfyUI browser UI. Add a short link/section in the ComfyPress README without rewriting its existing dirty content.

## Task 7: Acceptance and private GitHub publication

Run gateway pytest, PHP and JavaScript harnesses, Docker Compose config/build/smoke checks, `git diff --check`, secret scan, and readback of all changed files. Verify the public listener is not required and that unauthenticated API calls never reach the upstream. Create `SPhillips1337/comfypress-gateway` as a private repository (the existing ComfyPress repository is private), push only the new gateway repository after verification, then fetch/read back the remote URL, visibility, and commit contents. Do not commit or push the existing ComfyPress checkout.
