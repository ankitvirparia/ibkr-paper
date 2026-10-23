"""Read live account state from the guarded IBKR paper session."""
from __future__ import annotations

from datetime import datetime, timezone
import threading

from ..ibkr_client import IBKRClient, IBKRError

PAPER_ACCOUNT = "DUT160850"
_session_initialized = False
_session_lock = threading.Lock()


class SessionNotLive(RuntimeError):
    """The gateway is not authenticated; no local state can substitute."""


class AccountGuardError(RuntimeError):
    """The brokerage session exposed an account other than the paper account."""


def _amount(value) -> float:
    if isinstance(value, dict):
        value = value.get("amount", value.get("value", 0))
    if value is None or value == "":
        return 0.0
    return float(str(value).replace(",", ""))


def _field(mapping: dict, name: str):
    key = name.casefold()
    return next((value for k, value in mapping.items()
                 if str(k).casefold() == key), 0)


def _cash_by_currency(ledger: dict) -> dict[str, float]:
    cash = {}
    for currency, values in ledger.items():
        if str(currency).upper() == "BASE" or not isinstance(values, dict):
            continue
        amount = _field(values, "cashbalance")
        if amount == 0 and "amount" in values:
            amount = values
        if amount != 0:
            cash[str(currency).upper()] = _amount(amount)
    return cash


def _account_ids(response) -> list[str]:
    if isinstance(response, dict):
        response = response.get("accounts", [])
    if not isinstance(response, list):
        return []
    ids = []
    for account in response:
        if isinstance(account, dict):
            account = account.get("accountId") or account.get("account")
        if account is not None:
            ids.append(str(account))
    return ids


def ensure_session(client: IBKRClient) -> None:
    """Check authentication on every use and initialize brokerage once."""
    global _session_initialized
    try:
        status = client.auth_status()
    except IBKRError as exc:
        raise SessionNotLive("IBKR paper session is not live") from exc
    except Exception as exc:
        raise SessionNotLive("IBKR paper session is not live") from exc
    if not isinstance(status, dict) or not status.get("authenticated"):
        raise SessionNotLive("IBKR paper session is not live")

    if _session_initialized:
        return
    with _session_lock:
        if _session_initialized:
            return
        try:
            accounts = _account_ids(client.iserver_accounts())
        except IBKRError as exc:
            raise SessionNotLive("IBKR paper session is not live") from exc
        except Exception as exc:
            raise SessionNotLive("IBKR paper session is not live") from exc
        if accounts != [PAPER_ACCOUNT]:
            raise AccountGuardError(
                f"refusing gateway accounts {accounts!r}; expected [{PAPER_ACCOUNT!r}]")
        _session_initialized = True


def get_account_state(client: IBKRClient | None = None) -> dict:
    """Fetch a fresh, guarded account snapshot; never return cached balances."""
    if client is None:
        from ..api import load_cfg, make_client
        client = make_client(load_cfg())
    ensure_session(client)
    try:
        positions = client.positions(PAPER_ACCOUNT)
        summary = client.account_summary(PAPER_ACCOUNT)
        ledger = client.account_ledger(PAPER_ACCOUNT)
    except IBKRError as exc:
        raise SessionNotLive("IBKR paper session is not live") from exc
    except Exception as exc:
        raise SessionNotLive("IBKR paper session is not live") from exc

    if not isinstance(summary, dict) or not isinstance(ledger, dict):
        raise SessionNotLive("IBKR returned an invalid account-state response")
    if not isinstance(positions, list) or any(
            isinstance(position, dict) and "error" in position for position in positions):
        raise SessionNotLive("IBKR returned an invalid positions response")
    if isinstance(summary, dict) and "error" in summary:
        raise SessionNotLive("IBKR returned an account-summary error")
    if isinstance(ledger, dict) and "error" in ledger:
        raise SessionNotLive("IBKR returned an account-ledger error")
    try:
        account_values = {
            "net_liquidation": _amount(_field(summary, "netliquidation")),
            "buying_power": _amount(_field(summary, "buyingpower")),
            "available_funds": _amount(_field(summary, "availablefunds")),
            "gross_position_value": _amount(_field(summary, "grosspositionvalue")),
        }
        cash_by_currency = _cash_by_currency(ledger)
    except (TypeError, ValueError) as exc:
        raise SessionNotLive("IBKR returned invalid account-state values") from exc
    return {
        "account_id": PAPER_ACCOUNT,
        "positions": positions,
        "cash_by_currency": cash_by_currency,
        **account_values,
        "source": "ibkr-paper-live",
        "fetched_at": datetime.now(timezone.utc).isoformat(),
    }
