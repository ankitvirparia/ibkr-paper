"""FastAPI service: paper-trading signals + read-only IBKR views."""
from __future__ import annotations

from pathlib import Path

import yaml
from fastapi import FastAPI, HTTPException, Request

from .engine.paper_ledger import PaperLedger
from .engine.runner import run_cycle
from .ibkr_client import IBKRClient, IBKRError
from .strategies import STRATEGIES

CFG_PATH = Path(__file__).resolve().parent.parent / "config.yaml"

app = FastAPI(title="ibkr-paper", version="0.1.0")


def load_cfg() -> dict:
    with open(CFG_PATH) as f:
        return yaml.safe_load(f)


def make_client(cfg: dict) -> IBKRClient:
    g = cfg["gateway"]
    return IBKRClient(g["base_url"], verify_ssl=g.get("verify_ssl", False),
                      timeout=g.get("timeout", 15))


def make_ledger(cfg: dict) -> PaperLedger:
    p = cfg["paper"]
    return PaperLedger(p["db_path"], float(p["starting_cash"]))


@app.get("/health")
def health():
    return {"ok": True, "service": "ibkr-paper"}


@app.get("/strategies")
def strategies():
    cfg = load_cfg()
    out = []
    for name, cls in STRATEGIES.items():
        inst = cls(cfg.get("strategies", {}).get(name, {}))
        out.append({"name": name, "sleeve": inst.sleeve, "kind": inst.kind,
                    "params": inst.params})
    return out


@app.get("/ibkr/auth")
def ibkr_auth():
    try:
        return make_client(load_cfg()).auth_status()
    except IBKRError as e:
        raise HTTPException(503, str(e))


@app.get("/ibkr/accounts")
def ibkr_accounts():
    try:
        return make_client(load_cfg()).accounts()
    except IBKRError as e:
        raise HTTPException(503, str(e))


@app.get("/ibkr/positions")
def ibkr_positions(account: str):
    try:
        return make_client(load_cfg()).positions(account)
    except IBKRError as e:
        raise HTTPException(503, str(e))


@app.post("/signals/run")
def signals_run():
    """Run one paper cycle: strategies -> paper fills. Never touches real orders."""
    cfg = load_cfg()
    try:
        return run_cycle(cfg, make_client(cfg), make_ledger(cfg))
    except IBKRError as e:
        raise HTTPException(503, str(e))


@app.get("/paper/signals")
def paper_signals(limit: int = 100):
    return make_ledger(load_cfg()).signals(limit)


@app.get("/paper/positions")
def paper_positions():
    return make_ledger(load_cfg()).positions()


@app.get("/paper/pnl")
def paper_pnl():
    return make_ledger(load_cfg()).pnl({})


# -- self-contained gateway login (mobile-friendly) ---------------------------
# Serves a fully inlined copy of the gateway's JS-driven login page (a phone
# only has to load ONE page) and reverse-proxies the /sso/* calls it makes.
# The user types their own credentials; this service only relays bytes and
# never sees or stores the password.
from .sso_login import (  # noqa: E402
    LOGIN_PAGE,
    diag_beacon,
    login_page_response,
    proxy_to_gateway,
)


@app.get("/diag")
async def diag(request: Request):
    return await diag_beacon(request)


@app.api_route(
    "/sso/{path:path}",
    methods=["GET", "POST", "PUT", "DELETE", "OPTIONS", "HEAD", "PATCH"],
)
async def sso_proxy(path: str, request: Request):
    if path == "Login":
        if not LOGIN_PAGE.exists():
            raise HTTPException(503, "login page not built yet")
        return login_page_response()
    return await proxy_to_gateway(request, "/sso/" + path)


@app.api_route(
    "/portal.proxy/{path:path}",
    methods=["GET", "POST", "PUT", "DELETE", "OPTIONS", "HEAD", "PATCH"],
)
async def portal_proxy(path: str, request: Request):
    return await proxy_to_gateway(request, "/portal.proxy/" + path)


# Static assets for the inlined login page (gateway CSS/JS/images/fonts).
# Must come after the API routes so they dont shadow them.

# Static assets for the inlined login page (gateway CSS/JS/images/fonts).
# Must come after the API routes so they don't shadow them.
_ASSET_PREFIXES = ("css", "scripts", "images", "fonts", "en")


@app.api_route(
    "/{prefix}/{path:path}",
    methods=["GET", "POST", "PUT", "DELETE", "OPTIONS", "HEAD", "PATCH"],
)
async def gateway_assets(prefix: str, path: str, request: Request):
    if prefix not in _ASSET_PREFIXES:
        raise HTTPException(404, "not found")
    return await proxy_to_gateway(request, "/" + prefix + "/" + path)
