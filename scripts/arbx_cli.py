#!/usr/bin/env python3
"""
ARBX Command Line Interface
============================
Run from the project root:
  python -m scripts.arbx_cli <command> [args]

Or via Docker exec:
  docker exec arb-brain python -m scripts.arbx_cli <command>

Commands
--------
  workers list              List all live workers with status
  workers rejoin            Ask all workers to re-register
  workers reload            Reload config on all workers
  workers kill <id>         Kill a specific worker
  workers kill-all          Kill all workers

  spawn <exchange> <pairs>  Spawn a new worker  e.g. spawn binance BTC/USDT,ETH/USDT
  spawn <exchange> ALL      Spawn worker with all pairs

  fleet status              Show fleet health summary
  fleet events              Show recent fleet events

  graph paths               Show current arbitrage paths
  graph config              Show graph engine config

  events                    Show recent financial events
  events arbit              Show arbitrage events only
  events cr9am              Show 9AM CR events only

  logs tail [N]             Show last N log lines (default 50)

  config show               Show active config snapshot
  config reload             Trigger brain config reload
"""
from __future__ import annotations

import json
import os
import sys
from typing import Optional

# Use the brain's API — works both locally and inside the container
API_BASE = os.getenv("ARBX_API", "http://localhost:8000/api")

try:
    import urllib.request
    import urllib.error

    def _get(path: str) -> dict:
        url = f"{API_BASE}{path}"
        try:
            with urllib.request.urlopen(url, timeout=5) as r:
                return json.loads(r.read())
        except urllib.error.URLError as e:
            _die(f"Cannot reach brain API at {url}: {e}")

    def _post(path: str, data: dict = None) -> dict:
        url = f"{API_BASE}{path}"
        body = json.dumps(data or {}).encode()
        req  = urllib.request.Request(url, data=body,
               headers={"Content-Type": "application/json"}, method="POST")
        try:
            with urllib.request.urlopen(req, timeout=5) as r:
                return json.loads(r.read())
        except urllib.error.URLError as e:
            _die(f"Cannot reach brain API at {url}: {e}")

except ImportError:
    _die("urllib not available")


def _die(msg: str) -> None:
    print(f"✗ {msg}", file=sys.stderr)
    sys.exit(1)


def _ok(msg: str) -> None:
    print(f"✓ {msg}")


def _header(title: str) -> None:
    print(f"\n{'─'*60}")
    print(f"  {title}")
    print(f"{'─'*60}")


# ── Workers ───────────────────────────────────────────────────────────────────

def cmd_workers_list():
    data = _get("/fleet/workers")
    workers = data.get("workers", [])
    if not workers:
        print("No workers registered.")
        return

    _header(f"Workers ({len(workers)} total)")
    fmt = "  {:<35} {:<10} {:<10} {:<8} {:<6}"
    print(fmt.format("WORKER ID", "EXCHANGE", "STATUS", "PAIRS", "DEAD"))
    print("  " + "─" * 75)
    for w in sorted(workers, key=lambda x: x.get("exchange","")):
        dead = "✗" if w.get("is_dead") else "✓"
        print(fmt.format(
            w.get("worker_id","")[:34],
            w.get("exchange","")[:9],
            w.get("status","")[:9],
            str(len(w.get("pairs",[]))),
            dead,
        ))
    live = sum(1 for w in workers if not w.get("is_dead"))
    print(f"\n  Live: {live}/{len(workers)}")


def cmd_workers_rejoin():
    data = _post("/workers/all/reload")
    _ok(f"Re-join signal sent to all workers: {data}")


def cmd_workers_reload():
    data = _post("/workers/all/reload")
    _ok(f"Reload signal sent: {data}")


def cmd_workers_kill(worker_id: str):
    data = _post(f"/fleet/workers/{worker_id}/kill")
    _ok(f"Kill signal sent to {worker_id}: {data}")


def cmd_workers_kill_all():
    confirm = input("Kill ALL workers? (yes/no): ").strip().lower()
    if confirm != "yes":
        print("Aborted.")
        return
    data = _post("/workers/all/kill")
    _ok(f"Kill-all sent: {data}")


def cmd_spawn(exchange: str, pairs: str):
    data = _post("/workers/spawn", {"exchange": exchange, "pairs": pairs.split(",") if pairs != "ALL" else ["ALL"]})
    _ok(f"Spawn request sent for {exchange}: {data}")


# ── Fleet ─────────────────────────────────────────────────────────────────────

def cmd_fleet_status():
    data    = _get("/fleet/workers")
    workers = data.get("workers", [])

    by_exchange: dict = {}
    for w in workers:
        ex = w.get("exchange", "unknown")
        by_exchange.setdefault(ex, []).append(w)

    _header("Fleet Status")
    for ex, wlist in sorted(by_exchange.items()):
        live = sum(1 for w in wlist if not w.get("is_dead"))
        pairs_total = sum(len(w.get("pairs",[])) for w in wlist)
        status = "✓" if live == len(wlist) else f"⚠ {live}/{len(wlist)}"
        print(f"  {ex:<15} {status:<8} {len(wlist)} worker(s)  {pairs_total} pairs")

    total_live = sum(1 for w in workers if not w.get("is_dead"))
    print(f"\n  Total: {total_live}/{len(workers)} workers live")


def cmd_fleet_events():
    data   = _get("/fleet/events?limit=20")
    events = data.get("events", [])
    _header("Fleet Events (last 20)")
    for e in events:
        print(f"  [{e.get('level','INFO'):<8}] {e.get('timestamp','')[:19]}  {e.get('message','')}")


# ── Graph ─────────────────────────────────────────────────────────────────────

def cmd_graph_paths():
    data  = _get("/graph/paths")
    paths = data.get("paths", [])
    algo  = data.get("algorithm", "?")

    _header(f"Graph Arbitrage Paths (algo: {algo})")
    if not paths:
        print("  No profitable paths detected.")
        return
    for p in paths[:10]:
        net = p.get("net_profit_pct", 0)
        print(f"  {net:+.3f}%  {p.get('path','')}")


def cmd_graph_config():
    data = _get("/graph/config")
    _header("Graph Config")
    for k, v in data.items():
        if k != "note":
            print(f"  {k:<25} {v}")


# ── Events ────────────────────────────────────────────────────────────────────

def cmd_events(category: str = ""):
    url  = f"/events?limit=30" + (f"&category={category.upper()}" if category else "")
    data = _get(url)
    evts = data.get("events", [])
    stats = data.get("stats", {})

    _header(f"Financial Events{' — ' + category.upper() if category else ''}")
    print(f"  Stats: " + "  ".join(f"{k}={v}" for k,v in stats.items() if v))
    print()
    for e in evts:
        import datetime
        ts = datetime.datetime.fromtimestamp(e.get("ts",0)).strftime("%H:%M:%S")
        print(f"  {ts}  [{e.get('category','?'):<6}] [{e.get('level','INFO'):<7}]  {e.get('title','')}")
        if e.get("detail"):
            print(f"         {e['detail']}")


# ── Logs ──────────────────────────────────────────────────────────────────────

def cmd_logs(n: int = 50):
    data = _get(f"/logs?limit={n}")
    logs = data.get("logs", [])
    _header(f"Last {n} log lines")
    for line in logs:
        ts  = line.get("ts","")[:19]
        lvl = line.get("level","INFO")
        msg = line.get("message","")
        print(f"  {ts}  [{lvl:<8}]  {msg}")


# ── Config ────────────────────────────────────────────────────────────────────

def cmd_config_show():
    data = _get("/config/current")
    _header("Active Config")
    print(json.dumps(data, indent=2, default=str))


def cmd_config_reload():
    data = _post("/config/reload/brain")
    _ok(f"Brain config reloaded: {data.get('message','')}")


# ── Router ────────────────────────────────────────────────────────────────────

def main():
    args = sys.argv[1:]
    if not args:
        print(__doc__)
        return

    cmd = args[0].lower()
    sub = args[1].lower() if len(args) > 1 else ""

    if cmd == "workers":
        if sub == "list"    or sub == "":   cmd_workers_list()
        elif sub == "rejoin":               cmd_workers_rejoin()
        elif sub == "reload":               cmd_workers_reload()
        elif sub == "kill-all":             cmd_workers_kill_all()
        elif sub == "kill" and len(args) > 2: cmd_workers_kill(args[2])
        else: print(f"Unknown workers sub-command: {sub}")

    elif cmd == "spawn":
        if len(args) < 3:
            print("Usage: spawn <exchange> <pairs|ALL>")
        else:
            cmd_spawn(args[1], args[2])

    elif cmd == "fleet":
        if sub == "status"  or sub == "":   cmd_fleet_status()
        elif sub == "events":               cmd_fleet_events()
        else: print(f"Unknown fleet sub-command: {sub}")

    elif cmd == "graph":
        if sub == "paths"   or sub == "":   cmd_graph_paths()
        elif sub == "config":               cmd_graph_config()
        else: print(f"Unknown graph sub-command: {sub}")

    elif cmd == "events":
        cmd_events(sub)

    elif cmd == "logs":
        n = int(args[1]) if len(args) > 1 and args[1].isdigit() else 50
        cmd_logs(n)

    elif cmd == "config":
        if sub == "show":                   cmd_config_show()
        elif sub == "reload":               cmd_config_reload()
        else: print(f"Unknown config sub-command: {sub}")

    elif cmd in ("help", "--help", "-h"):
        print(__doc__)

    else:
        print(f"Unknown command: {cmd}")
        print("Run with 'help' to see available commands.")


if __name__ == "__main__":
    main()
