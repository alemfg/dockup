"""
Generate credentials for a new worker.

Usage:
    python scripts/generate_worker.py \\
        --id worker-binance-07 \\
        --exchange binance \\
        --pairs BTC/USDT ETH/USDT \\
        --expires 30

Outputs a .env file fragment with the WORKER_SECRET_KEY to deploy to the worker machine.
In production, this would be encrypted and bundled with the worker's mTLS certificates.
"""
import argparse
import secrets
import sys
from datetime import datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))


def main():
    parser = argparse.ArgumentParser(description="Generate worker credentials")
    parser.add_argument("--id",       required=True,  help="Worker ID")
    parser.add_argument("--exchange", required=True,  help="Exchange name")
    parser.add_argument("--pairs",    nargs="+",       default=[], help="Allowed pairs")
    parser.add_argument("--expires",  type=int,        default=30, help="Days until expiry")
    parser.add_argument("--executor", action="store_true",          help="Allow order execution")
    parser.add_argument("--max-order", type=float,    default=0.0,  help="Max order size USD")
    args = parser.parse_args()

    secret_key = secrets.token_hex(32)
    expires_at = datetime.utcnow() + timedelta(days=args.expires)

    print("\n" + "="*60)
    print(f"  Worker Credentials Generated")
    print("="*60)
    print(f"  Worker ID    : {args.id}")
    print(f"  Exchange     : {args.exchange}")
    print(f"  Pairs        : {', '.join(args.pairs) or 'all'}")
    print(f"  Can Execute  : {args.executor}")
    print(f"  Expires      : {expires_at.date()}")
    print("="*60)
    print("\n  Add to brain registry (run once on brain):")
    print(f"""
  from brain.security.auth_manager import AuthManager
  auth = AuthManager()
  auth.register_worker(
      worker_id="{args.id}",
      exchange="{args.exchange}",
      allowed_pairs={args.pairs or []},
      can_execute_orders={args.executor},
      max_order_size_usd={args.max_order},
      expires_days={args.expires},
  )
""")
    print("  Worker .env fragment (deploy to worker machine securely):")
    print(f"""
  WORKER_ID={args.id}
  EXCHANGE={args.exchange}
  PAIRS={','.join(args.pairs)}
  WORKER_SECRET_KEY={secret_key}
""")
    print("  ⚠  Store this secret key securely — it will not be shown again.\n")

    # Optionally write to file
    out = Path(f"{args.id}.env.secret")
    out.write_text(
        f"WORKER_ID={args.id}\n"
        f"EXCHANGE={args.exchange}\n"
        f"PAIRS={','.join(args.pairs)}\n"
        f"WORKER_SECRET_KEY={secret_key}\n"
    )
    print(f"  Written to: {out}  (keep private, do not commit)\n")


if __name__ == "__main__":
    main()
