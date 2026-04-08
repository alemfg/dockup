"""
ARBX Brain — entry point.

Usage:
  python -m scripts.run_brain
  python -m scripts.run_brain --api-port 8080 --metrics-port 9190
  python -m scripts.run_brain --config /path/to/config.yaml --log-level DEBUG

All options also settable via environment variables (env var takes priority):
  BRAIN_API_PORT=8080 python -m scripts.run_brain
  LOG_LEVEL=DEBUG BRAIN_API_PORT=8080 make brain
"""

import argparse
import asyncio
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))


def main():
    parser = argparse.ArgumentParser(
        prog="arbx-brain",
        description="ARBX Brain — central analysis and orchestration node.",
    )
    parser.add_argument(
        "--config",
        default=None,
        help="Path to config.yaml (default: config/config.yaml)",
    )
    parser.add_argument(
        "--api-port",
        type=int,
        default=None,
        help="Brain API port (default: $BRAIN_API_PORT or 8000)",
    )
    parser.add_argument(
        "--metrics-port",
        type=int,
        default=None,
        help="Prometheus metrics port (default: $BRAIN_METRICS_PORT or 9090)",
    )
    parser.add_argument(
        "--api-host",
        default=None,
        help="Brain API bind address (default: $BRAIN_API_HOST or 0.0.0.0)",
    )
    parser.add_argument(
        "--log-level",
        default=None,
        choices=["DEBUG", "INFO", "WARNING", "ERROR"],
        help="Log level (default: $LOG_LEVEL or INFO)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        default=None,
        help="Force dry-run mode (also set via DRY_RUN=true env var)",
    )

    args = parser.parse_args()

    # CLI args → environment variables (env vars already highest priority in config loader)
    if args.api_port:
        os.environ["BRAIN_API_PORT"]    = str(args.api_port)
    if args.metrics_port:
        os.environ["BRAIN_METRICS_PORT"] = str(args.metrics_port)
    if args.api_host:
        os.environ["BRAIN_API_HOST"]    = args.api_host
    if args.log_level:
        os.environ["LOG_LEVEL"]         = args.log_level
    if args.dry_run:
        os.environ["DRY_RUN"]           = "true"

    from brain.brain import run
    run(config_path=args.config)


if __name__ == "__main__":
    main()
