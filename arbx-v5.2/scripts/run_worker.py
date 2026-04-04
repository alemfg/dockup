"""
ARBX Worker — entry point with multiple pair input methods.

═══════════════════════════════════════════════════════
METHOD 1 — Environment variable (default, Docker-friendly)
═══════════════════════════════════════════════════════
  EXCHANGE=binance PAIRS=BTC/USDT,ETH/USDT python -m scripts.run_worker
  make worker EXCHANGE=binance PAIRS=BTC/USDT,ETH/USDT

═══════════════════════════════════════════════════════
METHOD 2 — CLI arguments
═══════════════════════════════════════════════════════
  python -m scripts.run_worker --exchange binance --pairs BTC/USDT ETH/USDT SOL/USDT
  python -m scripts.run_worker -e kraken -p BTC/USDT ETH/USDT

═══════════════════════════════════════════════════════
METHOD 3 — Pairs file (one pair per line)
═══════════════════════════════════════════════════════
  python -m scripts.run_worker --exchange binance --pairs-file config/pairs/binance.txt

  Example pairs file:
    BTC/USDT
    ETH/USDT
    SOL/USDT
    # Comments are ignored
    BNB/USDT

═══════════════════════════════════════════════════════
METHOD 4 — stdin pipe (cat, echo, or any shell pipeline)
═══════════════════════════════════════════════════════
  echo "BTC/USDT ETH/USDT SOL/USDT" | python -m scripts.run_worker --exchange binance --pairs-stdin
  cat config/pairs/binance.txt | python -m scripts.run_worker --exchange binance --pairs-stdin
  python -m scripts.run_worker --exchange binance --pairs-stdin <<EOF
  BTC/USDT
  ETH/USDT
  EOF

═══════════════════════════════════════════════════════
METHOD 5 — Runtime API reassignment (while worker is running)
═══════════════════════════════════════════════════════
  curl -X POST http://localhost:8000/api/workers/worker-binance-01/reassign \\
    -H "Content-Type: application/json" \\
    -d '["BTC/USDT", "ETH/USDT", "DOGE/USDT"]'

Priority order: CLI args > pairs-file > pairs-stdin > PAIRS env var
"""

import argparse
import asyncio
import os
import sys
from pathlib import Path
from typing import List

sys.path.insert(0, str(Path(__file__).parent.parent))

from worker.worker import Worker
from messaging.logging import get_logger, setup_logging

setup_logging()
logger = get_logger("scripts.run_worker")


# ─── Pair parsing helpers ─────────────────────────────────────────────────────

def _clean_pair(s: str) -> str:
    """Normalise a pair string — uppercase, strip whitespace."""
    s = s.strip().upper()
    # Accept both BTC/USDT and BTC-USDT
    if "-" in s and "/" not in s:
        s = s.replace("-", "/")
    return s


def _is_valid_pair(s: str) -> bool:
    return bool(s) and "/" in s and not s.startswith("#")


def pairs_from_args(pairs_raw: List[str]) -> List[str]:
    """Parse pairs from CLI --pairs argument (space or comma separated)."""
    result = []
    for item in pairs_raw:
        for p in item.replace(",", " ").split():
            cleaned = _clean_pair(p)
            if _is_valid_pair(cleaned):
                result.append(cleaned)
    return result


def pairs_from_file(path: str) -> List[str]:
    """Read pairs from a file — one per line, # comments ignored."""
    p = Path(path)
    if not p.exists():
        logger.error(f"Pairs file not found: {path}")
        sys.exit(1)

    pairs = []
    for line in p.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        # Accept comma-separated lines too
        for token in line.replace(",", " ").split():
            cleaned = _clean_pair(token)
            if _is_valid_pair(cleaned):
                pairs.append(cleaned)

    if not pairs:
        logger.error(f"No valid pairs found in {path}")
        sys.exit(1)

    logger.info(f"Loaded {len(pairs)} pairs from file: {path}")
    return pairs


def pairs_from_stdin() -> List[str]:
    """Read pairs from stdin — supports space, comma, or newline separated."""
    if sys.stdin.isatty():
        logger.error(
            "No data on stdin and --pairs-stdin was set.\n"
            "Usage: cat pairs.txt | python -m scripts.run_worker --exchange binance --pairs-stdin"
        )
        sys.exit(1)

    pairs = []
    for line in sys.stdin.read().splitlines():
        for token in line.replace(",", " ").split():
            cleaned = _clean_pair(token)
            if _is_valid_pair(cleaned):
                pairs.append(cleaned)

    if not pairs:
        logger.error("No valid pairs found on stdin")
        sys.exit(1)

    logger.info(f"Loaded {len(pairs)} pairs from stdin")
    return pairs


def pairs_from_env() -> List[str]:
    """Read pairs from PAIRS environment variable (comma-separated)."""
    raw = os.getenv("PAIRS", "BTC/USDT,ETH/USDT")
    pairs = [_clean_pair(p) for p in raw.split(",") if _clean_pair(p)]
    return [p for p in pairs if _is_valid_pair(p)]


def resolve_pairs(args: argparse.Namespace) -> List[str]:
    """
    Determine pairs from the highest-priority source available.
    Priority: CLI --pairs > --pairs-file > --pairs-stdin > PAIRS env var
    """
    if args.pairs:
        pairs = pairs_from_args(args.pairs)
        logger.info(f"Pairs from CLI args: {pairs}")
        return pairs

    if args.pairs_file:
        return pairs_from_file(args.pairs_file)

    if args.pairs_stdin:
        return pairs_from_stdin()

    # Fall back to environment variable
    pairs = pairs_from_env()
    logger.info(f"Pairs from PAIRS env var: {pairs}")
    return pairs


# ─── Main ─────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(
        prog="arbx-worker",
        description="ARBX Worker — streams exchange prices to the brain.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )

    # Exchange
    parser.add_argument(
        "-e", "--exchange",
        default=os.getenv("EXCHANGE", "binance"),
        help="Exchange name (default: $EXCHANGE or 'binance')",
    )

    # Pair input — mutually exclusive group
    pair_group = parser.add_mutually_exclusive_group()
    pair_group.add_argument(
        "-p", "--pairs",
        nargs="+",
        metavar="PAIR",
        help="Pairs to collect. Space or comma separated. e.g. BTC/USDT ETH/USDT",
    )
    pair_group.add_argument(
        "--pairs-file",
        metavar="FILE",
        help="Path to a pairs file (one pair per line, # comments allowed)",
    )
    pair_group.add_argument(
        "--pairs-stdin",
        action="store_true",
        help="Read pairs from stdin (pipe-friendly)",
    )

    # Other worker settings
    parser.add_argument(
        "--worker-id",
        default=os.getenv("WORKER_ID", ""),
        help="Worker identifier (auto-generated if not set)",
    )
    parser.add_argument(
        "--redis-host",
        default=os.getenv("REDIS_HOST", "localhost"),
        help="Redis host (default: $REDIS_HOST or 'localhost')",
    )
    parser.add_argument(
        "--redis-port",
        type=int,
        default=int(os.getenv("REDIS_PORT", "6379")),
        help="Redis port (default: $REDIS_PORT or 6379)",
    )
    parser.add_argument(
        "--tick-interval",
        type=int,
        default=int(os.getenv("TICK_INTERVAL_MS", "2000")),
        metavar="MS",
        help="Milliseconds between price fetches (default: $TICK_INTERVAL_MS or 2000)",
    )
    parser.add_argument(
        "--role",
        default=os.getenv("ROLE", "collector_only"),
        choices=["collector_only", "collector_and_executor"],
        help="Worker role",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        default=os.getenv("DRY_RUN", "true").lower() != "false",
        help="Simulation mode — no real exchange connection",
    )
    parser.add_argument(
        "--list-supported",
        action="store_true",
        help="Print supported exchanges and pairs, then exit",
    )

    args = parser.parse_args()

    if args.list_supported:
        print("\nSupported exchanges:")
        for ex in ["binance", "kraken", "coinbase", "bybit", "uniswap",
                   "sushiswap", "pancakeswap", "curve"]:
            print(f"  {ex}")
        print("\nExample pairs: BTC/USDT  ETH/USDT  SOL/USDT  BNB/USDT  XRP/USDT")
        print("               EUR/USD   ETH/BTC   WBTC/USDT  UNI/USDT")
        sys.exit(0)

    # Resolve pairs from the best available source
    pairs = resolve_pairs(args)

    if not pairs:
        logger.error("No pairs specified. Use --pairs, --pairs-file, --pairs-stdin, or PAIRS env var.")
        parser.print_help()
        sys.exit(1)

    # Override environment variables so Worker picks them up
    os.environ["EXCHANGE"]         = args.exchange
    os.environ["PAIRS"]            = ",".join(pairs)
    os.environ["REDIS_HOST"]       = args.redis_host
    os.environ["REDIS_PORT"]       = str(args.redis_port)
    os.environ["TICK_INTERVAL_MS"] = str(args.tick_interval)
    os.environ["ROLE"]             = args.role
    if args.worker_id:
        os.environ["WORKER_ID"]    = args.worker_id

    logger.info(
        f"Starting worker: exchange={args.exchange} "
        f"pairs={pairs} "
        f"redis={args.redis_host}:{args.redis_port}"
    )

    worker = Worker()
    asyncio.run(worker.start())


if __name__ == "__main__":
    main()
