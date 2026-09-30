"""Self-contained IBKR gateway login page + SSO reverse proxy.

Background: the gateway's stock /sso/Login page renders its login form via
JavaScript, which fails to appear in some mobile browsers. This module serves
a fully inlined single-file copy of that page (built by build_login_page.py,
so a phone only has to load ONE page) and reverse-proxies the /sso/* API
calls the page makes to the local gateway.

Security properties:
  - The user types their own IBKR credentials into their own browser.
  - This service only relays bytes; it never sees or stores the password.
  - The authenticated session cookies are captured into COOKIE_JAR so the
    server-side IBKRClient can reuse the same session for market data.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path

import httpx
from fastapi import Request
from fastapi.responses import FileResponse, Response

log = logging.getLogger("ibkr-paper.sso")

GW_BASE = "https://127.0.0.1:5000"
COOKIE_JAR = Path("/data/.ibkr_cookies.json")
LOGIN_PAGE = Path(__file__).resolve().parent.parent / "static" / "sso_login.html"
# uvicorn serves this app on this exact origin; used to rewrite redirects.
PUBLIC_ORIGIN_HOST = "100.101.82.11:8005"

# Hop-by-hop headers must not be relayed by a proxy.
_HOP_BY_HOP = {
    "connection", "keep-alive", "proxy-authenticate", "proxy-authorization",
    "te", "trailer", "transfer-encoding", "upgrade", "content-length",
    "content-encoding",
}


def load_session_cookies() -> dict:
    """Session cookies captured from a browser login via the proxy."""
    try:
        data = json.loads(COOKIE_JAR.read_text())
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def save_session_cookies(set_cookie_headers: list[str]) -> None:
    jar = load_session_cookies()
    changed = False
    for header in set_cookie_headers:
        pair = header.split(";", 1)[0]
        name, sep, value = pair.partition("=")
        name, value = name.strip(), value.strip()
        if sep and name and jar.get(name) != value:
            jar[name] = value
            changed = True
    if changed:
        COOKIE_JAR.parent.mkdir(parents=True, exist_ok=True)
        COOKIE_JAR.write_text(json.dumps(jar))
        log.info("captured %d session cookies -> %s", len(jar), COOKIE_JAR)


async def proxy_to_gateway(request: Request, gw_path: str) -> Response:
    """Relay one request to the local gateway, capturing session cookies."""
    body = await request.body()
    headers = {
        k: v for k, v in request.headers.items()
        if k.lower() not in ("host", "content-length", "connection")
    }
    url = GW_BASE + gw_path
    try:
        async with httpx.AsyncClient(verify=False, timeout=60.0) as client:
            r = await client.request(
                request.method,
                url,
                headers=headers,
                content=body,
                params=dict(request.query_params),
                follow_redirects=False,
            )
    except httpx.HTTPError as e:
        log.warning("gateway proxy error for %s: %s", gw_path, e)
        return Response(f"gateway unreachable: {e}", status_code=502)

    save_session_cookies(r.headers.get_list("set-cookie"))

    raw: list[tuple[bytes, bytes]] = []
    for k, v in r.headers.raw:
        kl = k.decode("latin-1").lower()
        if kl in _HOP_BY_HOP:
            continue
        if kl == "location":
            loc = v.decode("latin-1")
            loc = loc.replace("127.0.0.1:5000", PUBLIC_ORIGIN_HOST)
            loc = loc.replace("100.101.82.11:5000", PUBLIC_ORIGIN_HOST)
            v = loc.encode("latin-1")
        raw.append((k, v))

    resp = Response(content=r.content, status_code=r.status_code)
    resp.raw_headers = raw
    return resp


async def diag_beacon(request: Request) -> Response:
    """Log a diagnostic beacon from the inlined login page (never user data)."""
    params = dict(request.query_params)
    log.warning("LOGIN-DIAG from %s: %s",
                request.client.host if request.client else "?",
                {k: v[:200] for k, v in params.items()})
    return Response(status_code=204)


def login_page_response() -> FileResponse:
    return FileResponse(LOGIN_PAGE, media_type="text/html; charset=utf-8")
