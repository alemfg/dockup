"""
ARBX Price Injector — CLI entry point.

Injects synthetic prices into the brain's Redis stream, bypassing workers.
The brain responds exactly as if the prices came from a real exchange.

════════════════════════════════════════════════════════════════
METHOD 1 — Single price via command line
════════════════════════════════════════════════════════════════
  python -m scripts.inject --exchange binance --pair BTC/USDT --price 70000
  python -m scripts.inject -e binance -p BTC/USDT --price 70000

════════════════════════════════════════════════════════════════
METHOD 2 — Spread injection (two exchanges, one pair)
════════════════════════════════════════════════════════════════
  python -m scripts.inject --spread BTC/USDT \\
    --buy binance --buy-price 65000 \\
    --sell kraken --sell-price 66000

════════════════════════════════════════════════════════════════
METHOD 3 — JSON via curl (brain API endpoint)
════════════════════════════════════════════════════════════════
  # Single tick:
  curl -X POST http://localhost:8000/api/inject/tick \\
    -H "Content-Type: application/json" \\
    -d '{"exchange":"binance","pair":"BTC/USDT","price":70000}'

  # Multiple ticks:
  curl -X POST http://localhost:8000/api/inject/ticks \\
    -H "Content-Type: application/json" \\
    -d '[{"exchange":"binance","pair":"BTC/USDT","price":70000},
         {"exchange":"kraken","pair":"BTC/USDT","price":71000}]'

  # Named scenario:
  curl -X POST http://localhost:8000/api/inject/scenario \\
    -H "Content-Type: application/json" \\
    -d @config/scenarios/btc_pump.json

════════════════════════════════════════════════════════════════
METHOD 4 — JSON piped from stdin or file
════════════════════════════════════════════════════════════════
  # Single tick via echo:
  echo '{"exchange":"binance","pair":"BTC/USDT","price":70000}' \\
    | python -m scripts.inject --stdin

  # Multiple ticks via cat (JSON array):
  cat config/scenarios/btc_pump.json | python -m scripts.inject --stdin

  # File directly:
  python -m scripts.inject --scenario-file config/scenarios/btc_pump.yaml

════════════════════════════════════════════════════════════════
METHOD 5 — Interactive REPL
════════════════════════════════════════════════════════════════
  python -m scripts.inject --interactive

  Commands inside REPL:
    binance BTC/USDT 70000          set price
    kraken ETH/USDT 3200
    spread BTC/USDT binance 65000 kraken 66000
    scenario btc_pump               run a named scenario
    list                            list available scenarios
    watch                           show brain analysis for last tick
    help
    quit

════════════════════════════════════════════════════════════════
METHOD 6 — Graph cycle injection (for graph arbitrage testing)
════════════════════════════════════════════════════════════════
  python -m scripts.inject --cycle \\
    binance/BTC/USDT/65000 \\
    binance/ETH/BTC/0.0490 \\
    binance/ETH/USDT/3250

"""

import argparse
import asyncio
import json
import os
import sys
import yaml
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from injector.engine import PriceInjector, SyntheticTick, SyntheticCandle
from messaging.logging import get_logger, setup_logging

setup_logging()
logger = get_logger("scripts.inject")

SCENARIOS_DIR = Path(__file__).parent.parent / "config" / "scenarios"


# ─── Helpers ─────────────────────────────────────────────────────────────────

def load_scenario_file(path: str) -> dict:
    p = Path(path)
    if not p.exists():
        # Try the scenarios dir
        p = SCENARIOS_DIR / path
        if not p.exists():
            p = SCENARIOS_DIR / (path + ".yaml")
        if not p.exists():
            p = SCENARIOS_DIR / (path + ".json")
    if not p.exists():
        logger.error(f"Scenario file not found: {path}")
        sys.exit(1)
    with open(p) as f:
        if p.suffix in (".yaml", ".yml"):
            return yaml.safe_load(f)
        return json.load(f)


def list_scenarios() -> list:
    if not SCENARIOS_DIR.exists():
        return []
    return sorted([
        p.stem for p in SCENARIOS_DIR.iterdir()
        if p.suffix in (".yaml", ".yml", ".json")
    ])


def parse_cycle_arg(arg: str) -> tuple:
    """Parse 'binance/BTC/USDT/65000' → ('binance', 'BTC/USDT', 65000.0)"""
    parts = arg.split("/")
    if len(parts) != 4:
        logger.error(f"Bad cycle format: {arg}. Expected exchange/BASE/QUOTE/price")
        sys.exit(1)
    exchange, base, quote, price = parts
    return exchange, f"{base}/{quote}", float(price)


# ─── Interactive REPL ─────────────────────────────────────────────────────────

async def run_interactive(injector: PriceInjector, redis_host: str, api_port: int) -> None:
    print("\n╔══════════════════════════════════════════════════════════╗")
    print("║         ARBX Price Injector — Interactive Mode           ║")
    print("╠══════════════════════════════════════════════════════════╣")
    print("║  Commands:                                                ║")
    print("║    <exchange> <pair> <price>      inject a price tick    ║")
    print("║    spread <pair> <ex1> <p1> <ex2> <p2>  inject spread   ║")
    print("║    candle <ex> <pair> <tf> O H L C       inject candle  ║")
    print("║    cycle <ex/BASE/QUOTE/price> ...        inject cycle   ║")
    print("║    scenario <name or file>                run scenario   ║")
    print("║    list                                   list scenarios ║")
    print("║    watch                                  current graph  ║")
    print("║    clear                                  clear screen   ║")
    print("║    quit / exit                                           ║")
    print("╚══════════════════════════════════════════════════════════╝\n")

    while True:
        try:
            raw = input("inject> ").strip()
        except (EOFError, KeyboardInterrupt):
            print("\nBye.")
            break

        if not raw or raw.startswith("#"):
            continue

        parts = raw.split()
        cmd   = parts[0].lower()

        if cmd in ("quit", "exit", "q"):
            print("Bye.")
            break

        elif cmd == "clear":
            os.system("clear")

        elif cmd == "list":
            scenarios = list_scenarios()
            if scenarios:
                print("  Available scenarios:")
                for s in scenarios:
                    print(f"    {s}")
            else:
                print("  No scenario files found in config/scenarios/")

        elif cmd == "watch":
            import urllib.request
            try:
                url = f"http://localhost:{api_port}/api/graph/paths"
                with urllib.request.urlopen(url, timeout=3) as r:
                    data = json.loads(r.read())
                    paths = data.get("paths", [])
                    if paths:
                        print(f"\n  Graph paths ({len(paths)} found):")
                        for p in paths[:5]:
                            print(f"    {p['path']}  net={p['net_profit_pct']:.3f}%")
                    else:
                        print("  No profitable paths found yet.")
            except Exception as e:
                print(f"  Could not reach API: {e}")

        elif cmd == "scenario":
            if len(parts) < 2:
                print("  Usage: scenario <name or file>")
                continue
            scenario = load_scenario_file(parts[1])
            await injector.inject_scenario(scenario)

        elif cmd == "spread":
            # spread BTC/USDT binance 65000 kraken 66000
            if len(parts) != 6:
                print("  Usage: spread <pair> <buy_exchange> <buy_price> <sell_exchange> <sell_price>")
                continue
            await injector.inject_spread(
                pair=parts[1],
                buy_exchange=parts[2], buy_price=float(parts[3]),
                sell_exchange=parts[4], sell_price=float(parts[5]),
            )

        elif cmd == "candle":
            # candle binance BTC/USDT 1H 64000 65500 63800 65200
            if len(parts) != 8:
                print("  Usage: candle <exchange> <pair> <timeframe> <O> <H> <L> <C>")
                continue
            c = SyntheticCandle(
                exchange=parts[1], pair=parts[2], timeframe=parts[3],
                open=float(parts[4]), high=float(parts[5]),
                low=float(parts[6]), close=float(parts[7]),
            )
            await injector.inject_candle(c)

        elif cmd == "cycle":
            if len(parts) < 3:
                print("  Usage: cycle <ex/BASE/QUOTE/price> <ex/BASE/QUOTE/price> ...")
                continue
            ticks = [parse_cycle_arg(p) for p in parts[1:]]
            await injector.inject_graph_cycle(ticks)

        elif len(parts) == 3:
            # exchange pair price  (most common command)
            try:
                tick = SyntheticTick(
                    exchange=parts[0],
                    pair=parts[1],
                    price=float(parts[2]),
                )
                await injector.inject_tick(tick)
            except ValueError:
                print(f"  Bad price: {parts[2]}")

        else:
            print(f"  Unknown command: {cmd}. Type 'help' for commands.")


# ─── Main ─────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(
        prog="arbx-inject",
        description="Inject synthetic prices into the ARBX brain for testing.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )

    # Connection
    parser.add_argument("--redis-host", default=os.getenv("REDIS_HOST", "localhost"))
    parser.add_argument("--redis-port", type=int, default=int(os.getenv("REDIS_PORT", "6379")))
    parser.add_argument("--api-port",   type=int, default=int(os.getenv("BRAIN_API_PORT", "8000")))
    parser.add_argument("--quiet", "-q", action="store_true", help="Suppress output")

    sub = parser.add_subparsers(dest="mode", help="Injection mode")

    # ── tick ─────────────────────────────────────────────────────────────────
    p_tick = sub.add_parser("tick", help="Inject a single price tick")
    p_tick.add_argument("-e", "--exchange", required=True)
    p_tick.add_argument("-p", "--pair",     required=True)
    p_tick.add_argument("--price",          required=True, type=float)
    p_tick.add_argument("--volume",         type=float, default=50000)
    p_tick.add_argument("--note",           default="")
    p_tick.add_argument("--repeat",         type=int, default=1, help="Repeat N times")
    p_tick.add_argument("--interval",       type=float, default=0.0, help="Seconds between repeats")

    # ── spread ───────────────────────────────────────────────────────────────
    p_spread = sub.add_parser("spread", help="Inject prices on two exchanges (spatial arb test)")
    p_spread.add_argument("pair")
    p_spread.add_argument("--buy",       required=True, metavar="EXCHANGE")
    p_spread.add_argument("--buy-price", required=True, type=float)
    p_spread.add_argument("--sell",      required=True, metavar="EXCHANGE")
    p_spread.add_argument("--sell-price",required=True, type=float)
    p_spread.add_argument("--note",      default="")

    # ── candle ───────────────────────────────────────────────────────────────
    p_candle = sub.add_parser("candle", help="Inject an OHLCV candle (for CR model testing)")
    p_candle.add_argument("-e", "--exchange",  required=True)
    p_candle.add_argument("-p", "--pair",      required=True)
    p_candle.add_argument("--timeframe",       default="1H", choices=["1M","15M","1H"])
    p_candle.add_argument("--open",            required=True, type=float)
    p_candle.add_argument("--high",            required=True, type=float)
    p_candle.add_argument("--low",             required=True, type=float)
    p_candle.add_argument("--close",           required=True, type=float)
    p_candle.add_argument("--volume",          type=float, default=100)
    p_candle.add_argument("--time",            help="ISO8601 timestamp (default: now)")

    # ── cycle ────────────────────────────────────────────────────────────────
    p_cycle = sub.add_parser("cycle", help="Inject a graph arbitrage cycle (exchange/PAIR/price ...)")
    p_cycle.add_argument("legs", nargs="+", metavar="exchange/BASE/QUOTE/price")

    # ── scenario ─────────────────────────────────────────────────────────────
    p_scen = sub.add_parser("scenario", help="Run a scenario from a YAML/JSON file")
    p_scen.add_argument("name_or_file", help="Scenario name or path to .yaml/.json file")

    # ── stdin ────────────────────────────────────────────────────────────────
    p_stdin = sub.add_parser("stdin", help="Read JSON tick(s) from stdin or pipe")
    p_stdin.add_argument("--candles", action="store_true", help="Input is candles, not ticks")

    # ── list ─────────────────────────────────────────────────────────────────
    sub.add_parser("list", help="List available scenarios")

    # ── interactive ──────────────────────────────────────────────────────────
    sub.add_parser("interactive", help="Start interactive price injection REPL")

    args = parser.parse_args()

    async def run():
        injector = PriceInjector(
            redis_host=args.redis_host,
            redis_port=args.redis_port,
            verbose=not args.quiet,
        )
        await injector.connect()

        try:
            if args.mode == "tick" or args.mode is None and hasattr(args, "exchange"):
                for i in range(args.repeat):
                    await injector.inject_tick(SyntheticTick(
                        exchange=args.exchange,
                        pair=args.pair,
                        price=args.price,
                        volume_24h=args.volume,
                        note=args.note,
                    ))
                    if i < args.repeat - 1 and args.interval > 0:
                        await asyncio.sleep(args.interval)

            elif args.mode == "spread":
                await injector.inject_spread(
                    pair=args.pair,
                    buy_exchange=args.buy,   buy_price=args.buy_price,
                    sell_exchange=args.sell, sell_price=args.sell_price,
                    note=args.note,
                )

            elif args.mode == "candle":
                await injector.inject_candle(SyntheticCandle(
                    exchange=args.exchange,
                    pair=args.pair,
                    timeframe=args.timeframe,
                    open=args.open, high=args.high,
                    low=args.low,   close=args.close,
                    volume=args.volume,
                    time=args.time,
                ))

            elif args.mode == "cycle":
                ticks = [parse_cycle_arg(leg) for leg in args.legs]
                await injector.inject_graph_cycle(ticks)

            elif args.mode == "scenario":
                scenario = load_scenario_file(args.name_or_file)
                await injector.inject_scenario(scenario)

            elif args.mode == "stdin":
                raw = sys.stdin.read().strip()
                data = json.loads(raw)
                if isinstance(data, list):
                    for item in data:
                        if args.candles:
                            await injector.inject_candle(SyntheticCandle.from_dict(item))
                        else:
                            await injector.inject_tick(SyntheticTick.from_dict(item))
                elif isinstance(data, dict):
                    # Could be a scenario dict or a single tick
                    if "ticks" in data or "candles" in data or "name" in data:
                        await injector.inject_scenario(data)
                    elif args.candles:
                        await injector.inject_candle(SyntheticCandle.from_dict(data))
                    else:
                        await injector.inject_tick(SyntheticTick.from_dict(data))

            elif args.mode == "list":
                scenarios = list_scenarios()
                if scenarios:
                    print("\nAvailable scenarios:")
                    for s in scenarios:
                        print(f"  {s}")
                else:
                    print("No scenarios found in config/scenarios/")

            elif args.mode == "interactive":
                await run_interactive(injector, args.redis_host, args.api_port)

            else:
                parser.print_help()

        finally:
            await injector.disconnect()

    asyncio.run(run())


if __name__ == "__main__":
    main()
