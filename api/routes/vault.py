"""
Vault API (v6.0)
Endpoints for:
  - DB-backed config store (read/write persistent config)
  - API key management (store/list/delete exchange credentials)
  - Wallet address management
  - Fee tables (taker, withdrawal)
  - Rebalance transfer planning with network selection
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional
from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

router = APIRouter(tags=["Vault"])


def _cs(request: Request):
    """
    Get config_store for the current request.
    Uses the API's own asyncpg pool (created in the API's event loop) so it
    never crosses event-loop boundaries with the brain's pool.
    Falls back to the brain's pool if the API pool isn't ready yet.
    """
    # Preferred: API's own pool (same event loop as the route handlers)
    cs = getattr(request.app.state, "api_config_store", None)
    if cs is not None and cs._pool is not None:
        return cs
    # Fallback: brain's pool (may work if both share the same loop in tests)
    cs = request.app.state.brain.persistence.config_store
    if cs is not None and cs._pool is not None:
        return cs
    raise HTTPException(503, "Config store not available — PostgreSQL may be down")


# ── Config store ──────────────────────────────────────────────────────────────

class ConfigSetRequest(BaseModel):
    value:       Any
    category:    str = "general"
    description: str = ""
    is_secret:   bool = False


@router.get("/vault/config")
async def list_config(request: Request, category: Optional[str] = None):
    return {"items": await _cs(request).get_all(category)}


@router.get("/vault/config/{key}")
async def get_config(key: str, request: Request):
    cs  = _cs(request)
    val = await cs.get(key)
    if val is None:
        raise HTTPException(404, f"Config key '{key}' not found")
    return {"key": key, "value": val}


@router.put("/vault/config/{key}")
async def set_config(key: str, body: ConfigSetRequest, request: Request):
    await _cs(request).set(key, body.value, body.category, body.description, body.is_secret)
    return {"ok": True, "key": key}


@router.delete("/vault/config/{key}")
async def delete_config(key: str, request: Request):
    cs = _cs(request)
    async with cs._pool.acquire() as conn:
        await conn.execute("DELETE FROM arbx_config WHERE key=$1", key)
    return {"ok": True, "key": key}


# ── API Keys ──────────────────────────────────────────────────────────────────

class ApiKeyRequest(BaseModel):
    exchange:   str
    api_key:    str
    api_secret: str
    passphrase: str = ""
    label:      str = "main"
    sandbox:    bool = False


@router.get("/vault/apikeys")
async def list_api_keys(request: Request):
    return {"keys": await _cs(request).list_api_keys()}


@router.post("/vault/apikeys")
async def save_api_key(body: ApiKeyRequest, request: Request):
    if not body.api_key or not body.api_secret:
        raise HTTPException(400, "api_key and api_secret are required")
    uid = await _cs(request).save_api_key(
        body.exchange, body.api_key, body.api_secret,
        body.passphrase, body.label, body.sandbox
    )
    return {"ok": True, "id": uid, "exchange": body.exchange}


@router.delete("/vault/apikeys/{exchange}")
async def delete_api_key(exchange: str, request: Request, label: str = "main"):
    await _cs(request).delete_api_key(exchange, label)
    return {"ok": True}


@router.post("/vault/apikeys/{exchange}/test")
async def test_api_key(exchange: str, request: Request, label: str = "main"):
    """Fetch balance from exchange using stored credentials to verify they work."""
    creds = await _cs(request).get_api_key(exchange, label)
    if not creds:
        raise HTTPException(404, f"No API key stored for {exchange}/{label}")
    try:
        import ccxt.async_support as ccxt_async
        cls = getattr(ccxt_async, exchange, None)
        if not cls:
            raise HTTPException(400, f"Exchange '{exchange}' not supported by CCXT")
        ex = cls({"apiKey": creds["api_key"], "secret": creds["api_secret"],
                  "password": creds.get("passphrase", ""),
                  "sandbox": creds.get("sandbox", False)})
        try:
            bal = await ex.fetch_balance()
            total = bal.get("total", {})
            nonzero = {k: v for k, v in total.items() if v and v > 0}
            return {"ok": True, "exchange": exchange, "balances": nonzero,
                    "message": f"Connected — {len(nonzero)} assets with balance"}
        finally:
            await ex.close()
    except HTTPException:
        raise
    except Exception as e:
        return {"ok": False, "message": str(e)[:200]}


# ── Wallets ───────────────────────────────────────────────────────────────────

class WalletRequest(BaseModel):
    exchange: str
    coin:     str
    network:  str
    address:  str
    tag:      str = ""
    label:    str = ""


@router.get("/vault/wallets")
async def list_wallets(request: Request, exchange: Optional[str] = None):
    return {"wallets": await _cs(request).list_wallets(exchange)}


@router.post("/vault/wallets")
async def save_wallet(body: WalletRequest, request: Request):
    if not body.address:
        raise HTTPException(400, "address is required")
    uid = await _cs(request).save_wallet(
        body.exchange, body.coin, body.network, body.address, body.tag, body.label
    )
    return {"ok": True, "id": uid}


@router.delete("/vault/wallets/{wallet_id}")
async def delete_wallet(wallet_id: str, request: Request):
    await _cs(request).delete_wallet(wallet_id)
    return {"ok": True}


# ── Fees ──────────────────────────────────────────────────────────────────────

class FeeUpdateRequest(BaseModel):
    taker_pct: float
    maker_pct: Optional[float] = None


class WithdrawalFeeRequest(BaseModel):
    exchange:   str
    coin:       str
    network:    str
    fee_amount: float
    fee_usd:    float
    min_amount: float = 0.0


@router.get("/vault/fees")
async def get_fees(request: Request):
    return {"fees": await _cs(request).get_all_fees()}


@router.put("/vault/fees/{exchange}")
async def update_fee(exchange: str, body: FeeUpdateRequest, request: Request):
    await _cs(request).update_fee(exchange, body.taker_pct, body.maker_pct)
    return {"ok": True, "exchange": exchange}


@router.get("/vault/withdrawal-fees")
async def get_withdrawal_fees(request: Request,
                               exchange: Optional[str] = None,
                               coin: Optional[str] = None):
    return {"fees": await _cs(request).get_withdrawal_fees(exchange, coin)}


@router.post("/vault/withdrawal-fees")
async def upsert_withdrawal_fee(body: WithdrawalFeeRequest, request: Request):
    await _cs(request).update_withdrawal_fee(
        body.exchange, body.coin, body.network,
        body.fee_amount, body.fee_usd, body.min_amount
    )
    return {"ok": True}


# ── Transfer planning ─────────────────────────────────────────────────────────

class TransferPlanRequest(BaseModel):
    from_exchange: str
    to_exchange:   str
    coin:          str
    amount:        float


@router.post("/vault/transfer/plan")
async def plan_transfer(body: TransferPlanRequest, request: Request):
    """
    Return the cheapest network + estimated cost for a cross-exchange transfer.
    Does NOT execute anything.
    """
    cs   = _cs(request)
    best = await cs.best_network_for_transfer(body.from_exchange, body.to_exchange, body.coin)
    if not best:
        return {
            "ok": False,
            "message": f"No wallet found on {body.to_exchange} for {body.coin}, "
                       f"or no withdrawal fee data for {body.from_exchange}. "
                       f"Add a wallet address and check the fee table."
        }
    net_amount = body.amount - best["fee_amount"]
    if net_amount <= 0:
        return {"ok": False, "message": f"Amount {body.amount} {body.coin} is below the fee of {best['fee_amount']}"}
    return {
        "ok":           True,
        "from":         body.from_exchange,
        "to":           body.to_exchange,
        "coin":         body.coin.upper(),
        "amount":       body.amount,
        "network":      best["network"],
        "destination":  best["address"],
        "fee_amount":   best["fee_amount"],
        "fee_usd":      best["fee_usd"],
        "net_amount":   round(net_amount, 8),
        "min_amount":   best["min_amount"],
        "executable":   net_amount >= best["min_amount"],
        "note":         "Review carefully before executing. Transfers are irreversible.",
    }


@router.post("/vault/transfer/execute")
async def execute_transfer(body: TransferPlanRequest, request: Request,
                           confirm: bool = False):
    """
    Execute a cross-exchange transfer via CCXT withdrawal API.
    Requires confirm=true and a stored API key for from_exchange.
    """
    if not confirm:
        raise HTTPException(400, "confirm=true required. Transfers are irreversible.")

    cs    = _cs(request)
    creds = await cs.get_api_key(body.from_exchange)
    if not creds:
        raise HTTPException(404, f"No API key stored for {body.from_exchange}. "
                                 f"Add credentials in Vault → API Keys first.")

    best = await cs.best_network_for_transfer(body.from_exchange, body.to_exchange, body.coin)
    if not best:
        raise HTTPException(400, "No transfer route found. Check wallet addresses and fee table.")

    try:
        import ccxt.async_support as ccxt_async
        cls = getattr(ccxt_async, body.from_exchange, None)
        if not cls:
            raise HTTPException(400, f"Exchange '{body.from_exchange}' not in CCXT")

        ex = cls({"apiKey": creds["api_key"], "secret": creds["api_secret"],
                  "password": creds.get("passphrase", "")})
        try:
            result = await ex.withdraw(
                body.coin.upper(), body.amount, best["address"],
                tag=None,
                params={"network": best["network"]}
            )
            # Log to financial events
            try:
                from events.event_bus import emit_sync, Category, Level
                emit_sync(
                    category=Category.TRADE,
                    title=f"Transfer: {body.amount} {body.coin} → {body.to_exchange}",
                    detail=f"From {body.from_exchange} via {best['network']} | Fee: {best['fee_usd']:.2f} USD",
                    level=Level.INFO,
                    data={"result": result, "plan": best}
                )
            except Exception:
                pass
            return {"ok": True, "result": result, "network": best["network"],
                    "fee_usd": best["fee_usd"]}
        finally:
            await ex.close()
    except HTTPException:
        raise
    except Exception as e:
        return {"ok": False, "message": str(e)[:300]}
