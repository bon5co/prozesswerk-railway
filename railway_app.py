"""Run Prozesswerk on Railway: access key in front of it, IPv4 and IPv6 sockets.

Upstream has no authentication and POST /api/generate spends the deployer's LLM key, so anyone who
finds the public URL could burn it. This wrapper puts one credential in front of every route except
GET /api/health (the platform healthcheck). Accepted forms of the same credential:

  * HTTP Basic: user PROZESSWERK_USERNAME (default "admin"), secret PROZESSWERK_PASSWORD
    (the browser UI prompts for it)
  * Authorization: Bearer <PROZESSWERK_PASSWORD>
  * X-API-Key: <PROZESSWERK_PASSWORD>

If PROZESSWERK_PASSWORD is unset a random one is generated for the boot and printed in the deploy
log, so the service is never open.

Railway's healthcheck and edge reach the container over IPv4 while the private network is IPv6, and
uvicorn takes a single --host, so both sockets are opened here (same pattern as mem0-railway).
"""
import base64
import os
import secrets
import socket
import sys

sys.path.insert(0, "/app")

import uvicorn  # noqa: E402

from backend.main import app as upstream  # noqa: E402

USERNAME = os.environ.get("PROZESSWERK_USERNAME", "admin")
ACCESS_KEY = os.environ.get("PROZESSWERK_PASSWORD", "")
if not ACCESS_KEY:
    ACCESS_KEY = secrets.token_urlsafe(24)
    print("[railway] PROZESSWERK_PASSWORD not set; generated an access key for this boot: " + ACCESS_KEY, flush=True)


def _eq(a: str, b: str) -> bool:
    return secrets.compare_digest(a.encode(), b.encode())


def _authorised(headers: dict) -> bool:
    if "x-api-key" in headers and _eq(headers["x-api-key"], ACCESS_KEY):
        return True
    auth = headers.get("authorization", "")
    scheme, _, value = auth.partition(" ")
    scheme = scheme.lower()
    if scheme == "bearer":
        return _eq(value.strip(), ACCESS_KEY)
    if scheme == "basic":
        try:
            user, _, given = base64.b64decode(value.strip()).decode().partition(":")
        except Exception:
            return False
        return _eq(user, USERNAME) and _eq(given, ACCESS_KEY)
    return False


class Auth:
    def __init__(self, inner):
        self.inner = inner

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            await self.inner(scope, receive, send)
            return
        method, path = scope["method"], scope["path"]
        if (method in ("GET", "HEAD") and path == "/api/health") or method == "OPTIONS":
            await self.inner(scope, receive, send)
            return
        headers = {k.decode().lower(): v.decode() for k, v in scope["headers"]}
        if _authorised(headers):
            await self.inner(scope, receive, send)
            return
        body = b'{"detail":"Authentication required"}'
        await send({
            "type": "http.response.start",
            "status": 401,
            "headers": [
                (b"content-type", b"application/json"),
                (b"content-length", str(len(body)).encode()),
                (b"www-authenticate", b'Basic realm="Prozesswerk", charset="UTF-8"'),
            ],
        })
        await send({"type": "http.response.body", "body": body})


app = Auth(upstream)

if __name__ == "__main__":
    port = int(os.environ.get("PORT", "8080"))
    sockets = []
    v4 = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    v4.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    v4.bind(("0.0.0.0", port))
    sockets.append(v4)
    try:
        v6 = socket.socket(socket.AF_INET6, socket.SOCK_STREAM)
        v6.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        v6.setsockopt(socket.IPPROTO_IPV6, socket.IPV6_V6ONLY, 1)
        v6.bind(("::", port))
        sockets.append(v6)
    except OSError as exc:
        print(f"[railway] no IPv6 socket ({exc}); serving IPv4 only", flush=True)
    print(f"[railway] Prozesswerk listening on port {port} with {len(sockets)} socket(s)", flush=True)
    uvicorn.Server(uvicorn.Config(app, log_level="info")).run(sockets=sockets)
