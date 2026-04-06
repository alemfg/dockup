"""
Balances API (v6.2)
- Balance breakdown by exchange and asset
- Target allocation management (stored in DB config store)
- Rebalance suggestions with transfer routing via Vault
- Transfer execution (delegates to /vault/transfer/execute)
- P&L accounting: realized from order log + unrealized from open positions
"""
from __future__ import annotations

from typing import Dict, List, Optional
from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

router = APIRouter(tags=["Balances"])


def _cs(request: Request):
    """Config store using the API's own event-loop pool where possible."""
    cs = getattr(request.app.state, "api_config_store", None)
    if cs is not None and cs._pool is not None:
        return cs
    return request.app.state.brain.persistence.config_store


# ── Balance read endpoints ────────────────────────────────────────────────────

@router.get("/balances")
async def get_balances(request: Request):
    ms = request.app.state.brain.market_state
    return {
        "total_usd": round(ms.get_total_usd(), 2),
        "exchanges": ms.get_balances_by_exchange(),
        "all":       ms.get_all_balances(),
    }


@router.get("/balances/summary")
async def get_balance_summary(request: Request):
    """Full financial snapshot: balances + P&L + open positions value."""
    brain = request.app.state.brain
    ms    = brain.market_state

    total_usd    = round(ms.get_total_usd(), 2)
    by_exchange  = ms.get_balances_by_exchange()
    all_balances = ms.get_all_balances()

    # Per-exchange USD totals
    exchange_totals = {
        ex: round(sum(b.get("usd_value", 0) for b in bals), 2)
        for ex, bals in by_exchange.items()
    }

    # Per-asset totals across all exchanges
    from collections import defaultdict
    asset_totals: dict = defaultdict(lambda: {"total": 0.0, "usd_value": 0.0, "exchanges": []})
    for b in all_balances:
        asset = b.get("asset", "?")
        asset_totals[asset]["total"]     += b.get("total", 0)
        asset_totals[asset]["usd_value"] += b.get("usd_value", 0)
        asset_totals[asset]["exchanges"].append(b.get("exchange", "?"))

    # Realized P&L from order log
    order_summary = brain.order_log.financial_summary()
    pos_summary   = brain.position_tracker.get_pnl_summary()

    # Unrealized P&L from open positions
    open_positions  = brain.position_tracker.get_open_positions()
    unrealized_pnl  = sum(p.get("pnl_usd", 0) for p in open_positions)

    return {
        "total_usd":        total_usd,
        "exchange_totals":  exchange_totals,
        "asset_totals": {
            k: {"total": round(v["total"], 8), "usd_value": round(v["usd_value"], 2),
                "exchanges": list(set(v["exchanges"]))}
            for k, v in asset_totals.items()
            if v["usd_value"] > 0.01
        },
        "pnl": {
            "realized_usd":   order_summary.get("total_pnl_usd", 0.0),
            "unrealized_usd": round(unrealized_pnl, 2),
            "total_usd":      round(order_summary.get("total_pnl_usd", 0.0) + unrealized_pnl, 2),
            "total_trades":   order_summary.get("total_orders", 0),
            "win_rate":       order_summary.get("win_rate", 0.0),
            "total_fees_usd": order_summary.get("total_fees_usd", 0.0),
        },
        "open_positions":       len(open_positions),
        "open_positions_value": round(sum(p.get("capital_usd", 0) for p in open_positions), 2),
    }


# ── Target allocations ────────────────────────────────────────────────────────

class TargetAllocation(BaseModel):
    targets: Dict[str, float]   # {exchange: target_%}  must sum to ~100


@router.get("/balances/targets")
async def get_targets(request: Request):
    """Load saved target allocations from DB config store."""
    cs = _cs(request)
    if cs is None:
        return {"targets": {}}
    targets = await cs.get("balance.targets", default={})
    return {"targets": targets}


@router.put("/balances/targets")
async def save_targets(body: TargetAllocation, request: Request):
    """Save target allocations to DB config store."""
    total = sum(body.targets.values())
    if abs(total - 100.0) > 2.0:
        raise HTTPException(400, f"Targets must sum to ~100% (got {total:.1f}%)")
    cs = _cs(request)
    if cs is None:
        raise HTTPException(503, "Config store not available")
    await cs.set("balance.targets", body.targets, category="balances",
                 description="Target % allocation per exchange")
    return {"ok": True, "targets": body.targets}


# ── Rebalance suggestions ─────────────────────────────────────────────────────

class RebalanceRequest(BaseModel):
    target_pct:    Optional[Dict[str, float]] = None
    threshold_pct: float = 5.0
    coin:          str   = "USDT"


@router.post("/balances/rebalance/suggest")
async def suggest_rebalance(body: RebalanceRequest, request: Request):
    """
    Compute rebalance suggestions. If target_pct not provided, loads from DB.
    Returns transfer plan for each move including cheapest network via Vault.
    """
    brain = request.app.state.brain
    ms    = brain.market_state
    cs    = getattr(request.app.state, 'api_config_store', None) or brain.persistence.config_store

    # Load targets from DB if not provided
    target_pct = body.target_pct
    if not target_pct and cs:
        target_pct = await cs.get("balance.targets", default=None)

    raw_suggestions = ms.get_rebalance_suggestions(
        target_pct=target_pct,
        threshold_pct=body.threshold_pct,
    )

    # Enrich with transfer routing from Vault
    enriched = []
    for s in raw_suggestions:
        entry = dict(s)
        entry["coin"] = body.coin

        if s["action"] == "withdraw" and cs:
            # This exchange has excess — find where to send it
            for other in raw_suggestions:
                if other["action"] == "deposit":
                    route = await cs.best_network_for_transfer(
                        s["exchange"], other["exchange"], body.coin
                    )
                    if route:
                        entry["transfer_to"]     = other["exchange"]
                        entry["network"]         = route["network"]
                        entry["fee_usd"]         = route["fee_usd"]
                        entry["destination"]     = route["address"]
                        entry["net_amount_usd"]  = round(
                            s["amount_usd"] - route["fee_usd"], 2)
                        entry["executable"] = (
                            entry["net_amount_usd"] > 0
                            and bool(route["address"])
                        )
                    break
        enriched.append(entry)

    total_usd = round(ms.get_total_usd(), 2)
    return {
        "total_usd":   total_usd,
        "suggestions": enriched,
        "count":       len(enriched),
        "targets":     target_pct,
        "note": "Review each suggestion. Use 'Execute' to initiate a transfer via Vault.",
    }


class TransferApproval(BaseModel):
    from_exchange: str
    to_exchange:   str
    coin:          str
    amount:        float
    confirm:       bool = False


@router.post("/balances/rebalance/execute")
async def execute_rebalance_transfer(body: TransferApproval, request: Request):
    """
    Execute one approved rebalance transfer.
    Delegates to /vault/transfer/execute — requires API key in Vault.
    """
    if not body.confirm:
        raise HTTPException(400, "confirm=true required. Transfers are irreversible.")

    brain = request.app.state.brain
    cs    = getattr(request.app.state, 'api_config_store', None) or brain.persistence.config_store
    if cs is None:
        raise HTTPException(503, "Config store not available")

    creds = await cs.get_api_key(body.from_exchange)
    if not creds:
        raise HTTPException(404,
            f"No API key for {body.from_exchange}. Add credentials in Vault → API Keys.")

    route = await cs.best_network_for_transfer(body.from_exchange, body.to_exchange, body.coin)
    if not route:
        raise HTTPException(400,
            f"No transfer route found. Add a {body.coin} wallet for {body.to_exchange} in Vault → Wallets.")

    net_amount = body.amount - route["fee_amount"]
    if net_amount <= 0:
        raise HTTPException(400,
            f"Amount {body.amount} {body.coin} is below the fee of {route['fee_amount']}")

    try:
        import ccxt.async_support as ccxt_async
        cls = getattr(ccxt_async, body.from_exchange, None)
        if not cls:
            raise HTTPException(400, f"'{body.from_exchange}' not in CCXT")

        ex = cls({"apiKey": creds["api_key"], "secret": creds["api_secret"],
                  "password": creds.get("passphrase", "")})
        try:
            result = await ex.withdraw(
                body.coin.upper(), body.amount, route["address"],
                params={"network": route["network"]}
            )
        finally:
            await ex.close()

        # Emit financial event
        try:
            from events.event_bus import emit_sync, Category, Level
            emit_sync(
                category=Category.TRADE,
                title=f"Rebalance: {body.amount} {body.coin} {body.from_exchange}→{body.to_exchange}",
                detail=f"Via {route['network']} | Fee ~${route['fee_usd']:.2f}",
                level=Level.INFO,
            )
        except Exception:
            pass

        return {
            "ok":      True,
            "tx_id":   result.get("id", ""),
            "network": route["network"],
            "fee_usd": route["fee_usd"],
            "result":  result,
        }

    except HTTPException:
        raise
    except Exception as e:
        return {"ok": False, "message": str(e)[:300]}


@router.post("/balances/sync")
async def sync_balances(request: Request):
    """
    Force-sync balances from all exchanges immediately.
    Sends a 'fetch_balance' command to all live workers that have API keys
    (i.e. are in collector_and_executor or have a CCXT client).
    """
    brain   = request.app.state.brain
    workers = brain.fleet_monitor.get_all_workers()
    live    = [w for w in workers if not w.get("is_dead", True)]

    from datetime import datetime, timezone
    sent = 0
    for w in live:
        await brain.bus.publish_worker_command({
            "command":   "fetch_balance",
            "worker_id": w["worker_id"],
            "timestamp": datetime.now(timezone.utc).isoformat(),
        })
        sent += 1

    return {
        "ok":      True,
        "message": f"Balance sync command sent to {sent} worker(s). Data updates within ~5s.",
        "workers": sent,
    }
