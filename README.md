# ComfyPress Gateway

A small Docker Compose API gateway that puts a revocable bearer-key check in front of the ComfyUI endpoints used by ComfyPress. ComfyUI can remain installed and managed by Stability Matrix; this service does not need a GPU.

The gateway currently exposes only `POST /prompt`, `GET /history/{prompt_id}`, and `GET /view`. It does not proxy the ComfyUI browser UI or WebSocket API.

## Quick start

1. Install Docker Engine and the Compose plugin.
2. Copy `.env.example` to `.env` and set `COMFYUI_UPSTREAM` to the ComfyUI URL reachable from the container. The default `host.docker.internal` mapping works with Docker Desktop and is added for Linux Docker Engine. ComfyUI must listen on a host interface the gateway can reach. On Linux, if ComfyUI listens only on `127.0.0.1`, use the host-network override below.
3. Start the gateway:

   ```sh
   docker compose up --build -d
   docker compose ps
   ```

4. Create a site key. The secret is printed once; copy it directly to the WordPress server and do not put it in a workflow, browser script, source control, or public issue:

   ```sh
   docker compose run --rm gateway keys create --name wordpress-site
   ```

5. In ComfyPress, set the ComfyUI base URL to the gateway URL and enter the token in the **Gateway API token** setting. The plugin sends the key in the HTTP authorization header from the WordPress server; the token is not sent to visitors' browsers. For stronger at-rest protection, define `COMFY_IMAGE_GATEWAY_API_TOKEN` in `wp-config.php`; that constant takes precedence over the database setting.

The Compose port is bound to `127.0.0.1:8190` by default. The gateway uses a persistent Docker volume for key hashes. It does not persist plaintext tokens.

## Linux: ComfyUI listening on loopback

If ComfyUI is already bound only to `127.0.0.1:8188`, run the Linux host-network variant so the gateway can reach that listener without changing ComfyUI's bind address:

```sh
docker compose -f compose.yaml -f compose.linux-host.yaml up --build -d
```

In this mode the gateway also binds to host loopback (`127.0.0.1:8190`). The override is Linux-only; Docker Desktop users should use the regular Compose file and a ComfyUI address reachable through `host.docker.internal`.

## Cloudflare Tunnel and WordPress

Cloudflare Tunnel provides a public HTTPS route to the local gateway; the gateway's bearer key provides API authentication. The tunnel alone does not authorize ComfyPress requests.

1. Keep ComfyUI's own port private. Do not publish or route port `8188` through Cloudflare, a router, or a public reverse proxy. Route only to the gateway.
2. Configure a Cloudflare Tunnel public hostname such as `comfy-api.example.com` to forward to the local gateway service `http://127.0.0.1:8190` when `cloudflared` runs on the Docker host. Keep the Tunnel connector and Compose host on the same machine/network. Do not add an origin route that bypasses the gateway.
3. In ComfyPress, set the ComfyUI base URL to `https://comfy-api.example.com` and enter the generated gateway token. WordPress makes the API calls server-side, so the key is not sent to visitors' browsers.
4. Check that an unauthenticated request to the public hostname is rejected, then verify a ComfyPress request using the configured key.

Use HTTPS between WordPress and the public hostname. Treat each token as full permission to submit workflows and read generated images for this ComfyUI instance. Create separate keys per WordPress site, revoke lost keys, and keep WordPress administrator access and backups protected. Cloudflare Access interactive login is not a substitute for the gateway key; a service-token Access policy would require the WordPress client to send additional Access headers.

## Key management

```sh
docker compose run --rm gateway keys list
docker compose run --rm gateway keys revoke <key-id>
```

`keys list` shows labels and status, never secrets. Revocation takes effect on the next request. Anyone with Docker access to the host can manage gateway keys and should be treated as a gateway administrator.

## Configuration

| Variable | Default | Purpose |
|---|---|---|
| `COMFYUI_UPSTREAM` | `http://host.docker.internal:8188` | ComfyUI address reachable by the gateway |
| `GATEWAY_BIND_ADDRESS` | `127.0.0.1` | Host interface for the published gateway port |
| `GATEWAY_PORT` | `8190` | Host port used by Cloudflare Tunnel |
| `MAX_PROMPT_BODY_BYTES` | `2097152` | Maximum workflow request size (1 KiB–16 MiB) |
| `UPSTREAM_TIMEOUT_SECONDS` | `30` | ComfyUI request timeout (1–300 seconds) |

The gateway has no HTTP key-administration endpoint, no browser-facing UI, and no WebSocket proxy. Its unauthenticated `/healthz` response reports only `{"status":"ok"}`. All other exposed routes require a valid key.

## Development

```sh
python3 -m pip install -r requirements.txt
python3 -m pip install pytest
python3 -m pytest -q
```

The gateway uses only a fixed configured upstream. It does not accept a client-supplied target URL. Logs must not contain API keys, workflow bodies, prompts, or image data.
