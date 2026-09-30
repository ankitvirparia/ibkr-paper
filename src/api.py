"""FastAPI service: paper-trading signals, IBKR views, and human-gated
paper order routing (spec 004). The signal runner never places orders;
orders only flow through the /orders/* endpoints with an explicit ticket."""
from __future__ import annotations

from pathlib import Path

import yaml
from fastapi import FastAPI, HTTPException, Request

from .engine.broker import BrokerGuardError, BrokerRejected, PaperBroker
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


def make_broker(cfg: dict) -> PaperBroker:
    """Broker bound to the configured paper account. Refuses anything else."""
    return PaperBroker(make_client(cfg), cfg["paper"]["account_id"])


def _paper_account(cfg: dict) -> str:
    return cfg["paper"]["account_id"]


def _ticket_ttl(cfg: dict) -> int:
    return int(cfg["paper"].get("order_ticket_ttl_sec", 900))


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
def signals_run(strategy: str | None = None):
    """Run one paper cycle: strategies -> paper fills. Never touches real orders.

    Optional ?strategy=<name> runs a single strategy (used by the intraday cron).
    """
    cfg = load_cfg()
    if strategy and strategy not in STRATEGIES:
        raise HTTPException(404, f"unknown strategy {strategy}")
    try:
        return run_cycle(cfg, make_client(cfg), make_ledger(cfg), only=strategy)
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


# -- human-gated paper order routing (spec 004) ------------------------------
# Flow: POST /orders/preview -> (Ankit reviews ticket) ->
#       POST /orders/place {ticket_id, confirm:true, ...same params} ->
#       maybe POST /orders/confirm {ticket_id} for IBKR's reply handshake.
# The runner never calls these. Every placement needs an explicit confirm.


def _resolve_conid(client: IBKRClient, symbol: str, option: dict | None) -> int:
    if not option:
        return client.stock_conid(symbol)
    # v1: option conid comes from the greeks lookup (its response carries it).
    ucon = client.stock_conid(symbol)
    snap = client.snapshot([ucon], fields=["31"])
    price = float((snap[0].get("31") if snap else None) or 0)
    if not price:
        raise HTTPException(503, f"no quote for {symbol}, cannot resolve option")
    gr = client.option_greeks(ucon, option["expiry"], float(option["strike"]),
                              option.get("right", "P"), price)
    if not gr or not gr.get("conid"):
        raise HTTPException(503, f"cannot resolve option contract for {symbol}")
    return int(gr["conid"])


def _order_params(body: dict) -> dict:
    return {
        "symbol": body["symbol"],
        "side": body["side"],
        "qty": float(body["qty"]),
        "order_type": body.get("order_type", "MKT"),
        "limit_price": body.get("limit_price"),
        "tif": body.get("tif", "DAY"),
        "option": body.get("option"),
    }


def _orders_match_ignoring_coid(a: dict, b: dict) -> bool:
    return {k: v for k, v in a.items() if k != "cOID"} == \
           {k: v for k, v in b.items() if k != "cOID"}


@app.post("/orders/preview")
def orders_preview(body: dict):
    """Build the order, run IBKR's whatif margin preview, issue a ticket.

    Read-only against the account: previews place nothing."""
    cfg = load_cfg()
    try:
        p = _order_params(body)
        client = make_client(cfg)
        conid = _resolve_conid(client, p["symbol"], p["option"])
        order = PaperBroker.build_order(conid, p["side"], p["qty"],
                                        p["order_type"], p["limit_price"], p["tif"])
        whatif = make_broker(cfg).whatif(_paper_account(cfg), order)
    except (KeyError, ValueError) as e:
        raise HTTPException(400, f"bad order params: {e}")
    except IBKRError as e:
        raise HTTPException(503, str(e))
    ledger = make_ledger(cfg)
    ttl = _ticket_ttl(cfg)
    ticket_id = ledger.issue_ticket(order, signal_id=body.get("signal_id"),
                                    ttl_sec=ttl)
    ledger.record_broker_order(ticket_id, order, p["symbol"],
                               signal_id=body.get("signal_id"))
    return {"ticket_id": ticket_id, "symbol": p["symbol"], "side": p["side"],
            "qty": p["qty"], "order_type": p["order_type"],
            "limit_price": p["limit_price"], "tif": p["tif"], "conid": conid,
            "whatif": whatif, "expires_in_sec": ttl}


@app.post("/orders/place")
def orders_place(body: dict):
    """Place a previewed order. Requires the ticket AND the same params back;
    the ticket pins the exact order JSON (cOID excluded from the comparison)."""
    cfg = load_cfg()
    if not body.get("confirm"):
        raise HTTPException(400, "explicit confirm:true required to place")
    ticket_id = body.get("ticket_id")
    if not ticket_id:
        raise HTTPException(400, "ticket_id required")
    ledger = make_ledger(cfg)
    ticket = ledger.get_ticket(ticket_id)
    if ticket is None:
        raise HTTPException(400, "unknown ticket")
    import json
    stored = json.loads(ticket["order_json"])
    try:
        p = _order_params(body)
        client = make_client(cfg)
        conid = _resolve_conid(client, p["symbol"], p["option"])
        candidate = PaperBroker.build_order(conid, p["side"], p["qty"],
                                            p["order_type"], p["limit_price"], p["tif"])
    except (KeyError, ValueError) as e:
        raise HTTPException(400, f"bad order params: {e}")
    except IBKRError as e:
        raise HTTPException(503, str(e))
    if not _orders_match_ignoring_coid(candidate, stored):
        raise HTTPException(400, "order params do not match ticket — re-preview")
    try:
        ledger.redeem_ticket(ticket_id, stored)  # single-use, expiry enforced
        res = make_broker(cfg).place(_paper_account(cfg), stored)
    except BrokerGuardError as e:
        raise HTTPException(400, str(e))
    except BrokerRejected as e:
        bo = ledger.broker_order_by_ticket(ticket_id)
        if bo:
            ledger.update_broker_order(bo["id"], status="REJECTED")
        raise HTTPException(502, f"IBKR rejected the order: {e}")
    except IBKRError as e:
        raise HTTPException(503, str(e))
    bo = ledger.broker_order_by_ticket(ticket_id)
    if res.get("needs_confirm"):
        # IBKR wants an explicit nod to its precautionary warnings.
        # Nothing is placed yet — confirm via POST /orders/confirm.
        if bo:
            ledger.update_broker_order(bo["id"], status="NEEDS_CONFIRM",
                                       reply_id=res["reply_id"])
        return {"ticket_id": ticket_id, "needs_confirm": True,
                "reply_id": res["reply_id"], "warnings": res["messages"]}
    if bo:
        ledger.update_broker_order(bo["id"], status="PLACED",
                                   ibkr_order_id=res["order_id"])
    return {"ticket_id": ticket_id, "order_id": res["order_id"],
            "status": res["status"]}


@app.post("/orders/confirm")
def orders_confirm(body: dict):
    """Complete IBKR's precautionary reply handshake for a NEEDS_CONFIRM order."""
    cfg = load_cfg()
    ticket_id = body.get("ticket_id")
    if not ticket_id:
        raise HTTPException(400, "ticket_id required")
    ledger = make_ledger(cfg)
    bo = ledger.broker_order_by_ticket(ticket_id)
    if not bo or bo["status"] != "NEEDS_CONFIRM" or not bo["reply_id"]:
        raise HTTPException(400, "no pending IBKR confirmation for this ticket")
    try:
        res = make_broker(cfg).confirm(bo["reply_id"])
    except BrokerRejected as e:
        ledger.update_broker_order(bo["id"], status="REJECTED")
        raise HTTPException(502, f"IBKR rejected the confirmation: {e}")
    except IBKRError as e:
        raise HTTPException(503, str(e))
    ledger.update_broker_order(bo["id"], status="PLACED",
                               ibkr_order_id=res["order_id"])
    return {"ticket_id": ticket_id, "order_id": res["order_id"],
            "status": res["status"]}


@app.get("/orders")
def orders_list():
    """Local broker order records + live IBKR open orders (best effort)."""
    cfg = load_cfg()
    ledger = make_ledger(cfg)
    live = []
    try:
        live = make_broker(cfg).open_orders()
    except IBKRError:
        pass
    return {"local": ledger.broker_orders(), "ibkr_open": live}


@app.delete("/orders/{order_id}")
def orders_cancel(order_id: str):
    cfg = load_cfg()
    ledger = make_ledger(cfg)
    try:
        res = make_broker(cfg).cancel(_paper_account(cfg), order_id)
    except BrokerGuardError as e:
        raise HTTPException(400, str(e))
    except IBKRError as e:
        raise HTTPException(503, str(e))
    for bo in ledger.broker_orders(limit=200):
        if str(bo.get("ibkr_order_id")) == str(order_id):
            ledger.update_broker_order(bo["id"], status="CANCELLED")
    return {"order_id": order_id, "ibkr": res}


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
