"""
System Management API (v6.8)
Config export/import and database backup/restore.
"""
from __future__ import annotations

import asyncio
import gzip
import io
import json
import os
import subprocess
import tempfile
from datetime import datetime, timezone
from typing import Any, Dict

from fastapi import APIRouter, HTTPException, Request, Response, UploadFile, File
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

router = APIRouter(tags=["System Management"])


# ── Config Export / Import ────────────────────────────────────────────────────

def _build_config_snapshot(brain) -> Dict[str, Any]:
    """Build a portable config snapshot from the brain's live config + DB state."""
    cfg = brain.config
    snap: Dict[str, Any] = {
        "_meta": {
            "version":    str(cfg.brain.version),
            "exported_at": datetime.now(timezone.utc).isoformat(),
            "arbx_version": "6.8",
        },
        "trading": {
            "mode":               cfg.trading.mode.value,
            "min_profit_percent": cfg.trading.min_profit_percent,
            "max_position_usd":   cfg.trading.max_position_usd,
            "default_volume":     cfg.trading.default_volume,
            "slippage_percent":   cfg.trading.slippage_percent,
        },
        "risk": {
            "enabled":                cfg.risk.enabled,
            "max_daily_loss_usd":     cfg.risk.max_daily_loss_usd,
            "max_drawdown_pct":       cfg.risk.max_drawdown_pct,
            "max_consecutive_losses": cfg.risk.max_consecutive_losses,
            "max_exchange_exposure":  cfg.risk.max_exchange_exposure,
            "max_pair_exposure_usd":  cfg.risk.max_pair_exposure_usd,
        },
        "decision": {
            "enabled":              cfg.decision.enabled,
            "cr_min_score":         cfg.decision.cr_min_score,
            "cr_min_rr":            cfg.decision.cr_min_rr,
            "cr_require_bos":       cfg.decision.cr_require_bos,
            "cr_require_fvg":       cfg.decision.cr_require_fvg,
            "graph_min_profit_pct": cfg.decision.graph_min_profit_pct,
            "max_capital_per_trade": cfg.decision.max_capital_per_trade,
            "max_concurrent_orders": cfg.decision.max_concurrent_orders,
            "cooldown_seconds":      cfg.decision.cooldown_seconds,
        },
        "graph": {
            "algorithm":       cfg.graph.algorithm,
            "max_hops":        cfg.graph.max_hops,
            "min_hops":        cfg.graph.min_hops,
            "min_profit_pct":  cfg.graph.min_profit_pct,
            "stale_edge_s":    cfg.graph.stale_edge_s,
            "start_asset":     cfg.graph.start_asset,
            "hub_assets":      cfg.graph.hub_assets,
            "dex_max_gas_usd": cfg.graph.dex_max_gas_usd,
        },
        "workers": {
            "exchanges":         cfg.workers.exchanges,
            "pairs_worker_size": cfg.workers.pairs_worker_size,
        },
        "alerts": {
            "ntfy_enabled":     cfg.alerts.ntfy_enabled,
            "ntfy_url":         cfg.alerts.ntfy_url,
            "ntfy_topic":       cfg.alerts.ntfy_topic,
            "slack_enabled":    cfg.alerts.slack_enabled,
            "discord_enabled":  getattr(cfg.alerts, "discord_enabled", False),
            "telegram_enabled": getattr(cfg.alerts, "telegram_enabled", False),
            "email_enabled":    getattr(cfg.alerts, "email_enabled", False),
            "webhook_enabled":  cfg.alerts.webhook_enabled,
            # NOTE: secrets (webhooks, passwords) are intentionally excluded
        },
        "env_vars": {
            # Safe env vars — no secrets
            "TICK_INTERVAL_MS":        os.getenv("TICK_INTERVAL_MS", "2000"),
            "PAIRS_WORKER_SIZE":       os.getenv("PAIRS_WORKER_SIZE", "200"),
            "PAIRS_ALL_QUOTE_FILTER":  os.getenv("PAIRS_ALL_QUOTE_FILTER", "USDT,USDC,BTC,ETH"),
            "EXCHANGES":               os.getenv("EXCHANGES", ""),
            "TRADING_MODE":            os.getenv("TRADING_MODE", "disabled"),
            "LOG_LEVEL":               os.getenv("LOG_LEVEL", "INFO"),
            "HEARTBEAT_INTERVAL_S":    os.getenv("HEARTBEAT_INTERVAL_S", "10"),
            "HEARTBEAT_TTL":           os.getenv("HEARTBEAT_TTL", "45"),
            "GRAPH_ALGORITHM":         os.getenv("GRAPH_ALGORITHM", "bellman_ford"),
            "GRAPH_MIN_SPREAD_PCT":    os.getenv("GRAPH_MIN_SPREAD_PCT", "0.25"),
            "LISTING_ALERT_THRESHOLD_PCT": os.getenv("LISTING_ALERT_THRESHOLD_PCT", "5.0"),
        },
    }
    return snap


@router.get("/system/config/export")
async def export_config(request: Request):
    """
    Export current ARBX configuration as a JSON file.
    Secrets (API keys, webhook URLs, passwords) are intentionally excluded.
    Safe to share or commit.
    """
    brain = request.app.state.brain
    snap  = _build_config_snapshot(brain)
    body  = json.dumps(snap, indent=2).encode()
    ts    = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    return Response(
        content=body,
        media_type="application/json",
        headers={"Content-Disposition": f"attachment; filename=arbx_config_{ts}.json"},
    )


class ConfigImportBody(BaseModel):
    config: Dict[str, Any]
    dry_run: bool = True   # if true: validate only, don't apply


@router.post("/system/config/import")
async def import_config(body: ConfigImportBody, request: Request):
    """
    Import a config snapshot (from export). Applies overridable fields only.
    Secrets are never imported — add those via Vault or .env.local.
    Set dry_run=false to actually apply.
    """
    brain = request.app.state.brain
    snap  = body.config
    meta  = snap.get("_meta", {})
    applied: list = []
    warnings: list = []

    # Version compatibility check
    exported_version = meta.get("arbx_version", "unknown")
    if exported_version not in ("6.7", "6.8", "unknown"):
        warnings.append(f"Config was exported from v{exported_version} — some fields may not apply")

    if not body.dry_run:
        from config.loader import reload_config
        cfg = brain.config

        # Apply risk settings
        if "risk" in snap:
            r = snap["risk"]
            if "max_daily_loss_usd"     in r: cfg.risk.max_daily_loss_usd     = float(r["max_daily_loss_usd"]);     applied.append("risk.max_daily_loss_usd")
            if "max_drawdown_pct"        in r: cfg.risk.max_drawdown_pct        = float(r["max_drawdown_pct"]);        applied.append("risk.max_drawdown_pct")
            if "max_consecutive_losses"  in r: cfg.risk.max_consecutive_losses  = int(r["max_consecutive_losses"]);   applied.append("risk.max_consecutive_losses")
            if "max_exchange_exposure"   in r: cfg.risk.max_exchange_exposure   = float(r["max_exchange_exposure"]);   applied.append("risk.max_exchange_exposure")
            if "max_pair_exposure_usd"   in r: cfg.risk.max_pair_exposure_usd   = float(r["max_pair_exposure_usd"]);   applied.append("risk.max_pair_exposure_usd")

        # Apply decision settings
        if "decision" in snap:
            d = snap["decision"]
            if "cr_min_score"          in d: cfg.decision.cr_min_score          = float(d["cr_min_score"]);          applied.append("decision.cr_min_score")
            if "cr_min_rr"             in d: cfg.decision.cr_min_rr             = float(d["cr_min_rr"]);             applied.append("decision.cr_min_rr")
            if "cr_require_bos"        in d: cfg.decision.cr_require_bos        = bool(d["cr_require_bos"]);         applied.append("decision.cr_require_bos")
            if "graph_min_profit_pct"  in d: cfg.decision.graph_min_profit_pct  = float(d["graph_min_profit_pct"]); applied.append("decision.graph_min_profit_pct")
            if "max_capital_per_trade" in d: cfg.decision.max_capital_per_trade = float(d["max_capital_per_trade"]); applied.append("decision.max_capital_per_trade")
            if "cooldown_seconds"      in d: cfg.decision.cooldown_seconds      = int(d["cooldown_seconds"]);        applied.append("decision.cooldown_seconds")

        # Apply graph settings
        if "graph" in snap:
            g = snap["graph"]
            if "algorithm"     in g: cfg.graph.algorithm     = g["algorithm"];          applied.append("graph.algorithm")
            if "max_hops"      in g: cfg.graph.max_hops      = int(g["max_hops"]);      applied.append("graph.max_hops")
            if "min_profit_pct" in g: cfg.graph.min_profit_pct = float(g["min_profit_pct"]); applied.append("graph.min_profit_pct")

    return {
        "ok":       True,
        "dry_run":  body.dry_run,
        "applied":  applied,
        "warnings": warnings,
        "meta":     meta,
        "message":  f"{'Validated' if body.dry_run else 'Applied'} {len(applied)} settings",
    }


# ── Database Backup / Restore ─────────────────────────────────────────────────

def _pg_env(config) -> dict:
    """Build postgres env vars for pg_dump / psql commands."""
    return {
        **os.environ,
        "PGPASSWORD": os.getenv("POSTGRES_PASSWORD", config.postgres.password or ""),
        "PGHOST":     config.postgres.host,
        "PGPORT":     str(config.postgres.port),
        "PGUSER":     config.postgres.user,
        "PGDATABASE": config.postgres.database,
    }


@router.get("/system/backup")
async def create_backup(request: Request):
    """
    Create a PostgreSQL backup (pg_dump) and stream it as a gzip file.
    Contains: arbx_config, api_keys (encrypted), wallets, fees, order_log.
    Safe to store — API keys are encrypted at rest with ARBX_MASTER_KEY.
    """
    brain = request.app.state.brain
    env   = _pg_env(brain.config)
    ts    = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")

    try:
        proc = await asyncio.create_subprocess_exec(
            "pg_dump",
            "--no-owner", "--no-acl",
            "--format=plain",
            "--encoding=UTF8",
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            env=env,
        )
        stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=60)
        if proc.returncode != 0:
            raise HTTPException(500, f"pg_dump failed: {stderr.decode()[:500]}")

        # Gzip compress in memory
        buf = io.BytesIO()
        with gzip.GzipFile(fileobj=buf, mode="wb") as gz:
            gz.write(stdout)
        buf.seek(0)

        return StreamingResponse(
            buf,
            media_type="application/gzip",
            headers={"Content-Disposition": f"attachment; filename=arbx_backup_{ts}.sql.gz"},
        )
    except FileNotFoundError:
        raise HTTPException(500, "pg_dump not found — install postgresql-client in the brain container")
    except asyncio.TimeoutError:
        raise HTTPException(500, "pg_dump timed out (> 60s)")


@router.get("/system/backup/tables")
async def backup_tables_json(request: Request):
    """
    Export key DB tables as JSON (lighter alternative to full pg_dump).
    Includes: arbx_config, fee_table, withdrawal_fees, wallet_addresses.
    Excludes: api_keys (sensitive even encrypted), order_log (large).
    """
    brain = request.app.state.brain
    cs    = getattr(request.app.state, "api_config_store", None)
    if not cs or not cs._pool:
        raise HTTPException(503, "DB not available")

    tables: Dict[str, list] = {}
    ts = datetime.now(timezone.utc).isoformat()

    async with cs._pool.acquire() as conn:
        # arbx_config
        rows = await conn.fetch("SELECT key, value, category, description FROM arbx_config ORDER BY key")
        tables["arbx_config"] = [dict(r) for r in rows]

        # fee_table
        rows = await conn.fetch("SELECT * FROM fee_table ORDER BY exchange")
        tables["fee_table"] = [dict(r) for r in rows]

        # withdrawal_fees
        try:
            rows = await conn.fetch("SELECT * FROM withdrawal_fees ORDER BY exchange, coin, network")
            tables["withdrawal_fees"] = [dict(r) for r in rows]
        except Exception:
            tables["withdrawal_fees"] = []

        # wallet_addresses
        try:
            rows = await conn.fetch("SELECT exchange, coin, network, address, tag, label FROM wallet_addresses ORDER BY exchange")
            tables["wallet_addresses"] = [dict(r) for r in rows]
        except Exception:
            tables["wallet_addresses"] = []

    snap = {"_meta": {"exported_at": ts, "arbx_version": "6.8"}, "tables": tables}
    body = json.dumps(snap, indent=2, default=str).encode()
    date_str = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    return Response(
        content=body,
        media_type="application/json",
        headers={"Content-Disposition": f"attachment; filename=arbx_tables_{date_str}.json"},
    )


@router.post("/system/restore/tables")
async def restore_tables_json(request: Request):
    """
    Restore arbx_config and fee_table from a JSON export.
    Merges into existing data (upsert) — does not delete existing records.
    """
    body = await request.json()
    tables = body.get("tables", {})

    cs = getattr(request.app.state, "api_config_store", None)
    if not cs or not cs._pool:
        raise HTTPException(503, "DB not available")

    restored: Dict[str, int] = {}

    async with cs._pool.acquire() as conn:
        # Restore arbx_config
        if "arbx_config" in tables:
            count = 0
            for row in tables["arbx_config"]:
                await conn.execute(
                    """INSERT INTO arbx_config (key, value, category, description)
                       VALUES ($1, $2, $3, $4)
                       ON CONFLICT (key) DO UPDATE
                       SET value=$2, category=$3, description=$4""",
                    row["key"], str(row.get("value", "")),
                    row.get("category", "general"), row.get("description", "")
                )
                count += 1
            restored["arbx_config"] = count

        # Restore fee_table
        if "fee_table" in tables:
            count = 0
            for row in tables["fee_table"]:
                await conn.execute(
                    """INSERT INTO fee_table (exchange, taker_pct, maker_pct)
                       VALUES ($1, $2, $3)
                       ON CONFLICT (exchange) DO UPDATE
                       SET taker_pct=$2, maker_pct=$3""",
                    row["exchange"], float(row.get("taker_pct", 0.1)),
                    float(row.get("maker_pct", 0.1))
                )
                count += 1
            restored["fee_table"] = count

        # Restore wallet_addresses
        if "wallet_addresses" in tables:
            count = 0
            for row in tables["wallet_addresses"]:
                await conn.execute(
                    """INSERT INTO wallet_addresses (exchange, coin, network, address, tag, label)
                       VALUES ($1, $2, $3, $4, $5, $6)
                       ON CONFLICT DO NOTHING""",
                    row["exchange"], row["coin"], row["network"],
                    row["address"], row.get("tag", ""), row.get("label", "")
                )
                count += 1
            restored["wallet_addresses"] = count

    return {"ok": True, "restored": restored}
