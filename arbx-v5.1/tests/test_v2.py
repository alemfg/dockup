"""
ArbitrageEngine v2 — Test Suite
Run: pytest tests/test_v2.py -v
"""
import asyncio
import time
from datetime import datetime, timedelta
from typing import List
import pytest

# ─── Config ──────────────────────────────────────────────────────────────────

def test_config_loads_defaults():
    import sys; sys.path.insert(0, "/home/claude/arb-engine-v2")
    from config.loader import AppConfig
    cfg = AppConfig()
    assert cfg.brain.dry_run is True
    assert cfg.brain.version == "2.0.0"
    assert cfg.security.require_mtls is True
    assert cfg.analysis.cr_9am.timezone == "America/New_York"

# ─── Models ──────────────────────────────────────────────────────────────────

def test_cr_range_properties():
    import sys; sys.path.insert(0, "/home/claude/arb-engine-v2")
    from messaging.models import CRRange
    r = CRRange(timeframe="1H", candle_time=datetime.utcnow(), high=66000.0, low=64000.0)
    assert r.equilibrium == 65000.0
    assert r.size == 2000.0
    assert r.is_discount(64500.0) is True
    assert r.is_premium(65500.0) is True
    assert r.is_discount(65500.0) is False

def test_cr_signal_risk_reward():
    import sys; sys.path.insert(0, "/home/claude/arb-engine-v2")
    from messaging.models import CRRange, CRSignal, Sweep
    htf = CRRange("1H", datetime.utcnow(), high=66000.0, low=64000.0)
    ltf = CRRange("15M", datetime.utcnow(), high=65500.0, low=65000.0)
    sweep = Sweep("low_sweep", 64950.0, datetime.utcnow(), 65000.0, confirmed=True)

    signal = CRSignal(
        pair="BTC/USDT", exchange="binance",
        direction="long",
        htf_range=htf, ltf_range=ltf, sweep=sweep,
        bos_confirmed=True,
        order_block=None, fvg=None,
        ifvg_ob_alignment=False,
        entry_price=65050.0, entry_zone_top=65100.0, entry_zone_bottom=65000.0,
        tp1=65500.0, tp2=66000.0,
        stop_loss=64900.0,
        setup_score=0.75, confidence="HIGH",
    )

    assert signal.risk_reward_tp1 == pytest.approx(3.0, abs=0.1)
    assert signal.risk_reward_tp2 > signal.risk_reward_tp1
    d = signal.to_dict()
    assert d["direction"] == "long"
    assert d["targets"]["tp1"] == 65500.0
    assert d["quality"]["score"] == 0.75

def test_worker_heartbeat_to_dict():
    import sys; sys.path.insert(0, "/home/claude/arb-engine-v2")
    from messaging.models import WorkerHeartbeat, WorkerStatus, WorkerCondition
    hb = WorkerHeartbeat(
        worker_id="w-bin-01", exchange="binance",
        pairs=["BTC/USDT"], machine="192.168.1.1",
        status=WorkerStatus.HEALTHY, condition=WorkerCondition.NONE,
        ticks_last_60s=420, latency_ms=38.0,
        error_count=0, last_error=None,
        cpu_pct=18.0, memory_mb=124.0,
    )
    d = hb.to_dict()
    assert d["status"] == "healthy"
    assert d["condition"] == "none"
    assert d["latency_ms"] == 38.0

# ─── Auth Manager ────────────────────────────────────────────────────────────

def test_auth_manager_register_and_verify():
    import sys; sys.path.insert(0, "/home/claude/arb-engine-v2")
    from brain.security.auth_manager import AuthManager
    auth = AuthManager(nonce_ttl=30)

    secret = auth.register_worker(
        worker_id="w-test-01",
        exchange="binance",
        allowed_pairs=["BTC/USDT"],
    )
    assert len(secret) == 64   # hex32 = 64 chars

    msg = auth.sign_message({"worker_id": "w-test-01", "data": "hello"}, secret)
    valid, reason = auth.verify_message(msg, source_ip="127.0.0.1")
    assert valid is True
    assert reason == "OK"

def test_auth_manager_rejects_replay():
    import sys; sys.path.insert(0, "/home/claude/arb-engine-v2")
    from brain.security.auth_manager import AuthManager
    auth = AuthManager(nonce_ttl=30)
    secret = auth.register_worker("w-test-02", "kraken", [])

    msg = auth.sign_message({"worker_id": "w-test-02"}, secret)

    valid1, _ = auth.verify_message(msg)
    assert valid1 is True

    # Same message replayed — must fail
    valid2, reason = auth.verify_message(msg)
    assert valid2 is False
    assert "nonce" in reason.lower()

def test_auth_manager_rejects_unknown_worker():
    import sys; sys.path.insert(0, "/home/claude/arb-engine-v2")
    from brain.security.auth_manager import AuthManager
    auth = AuthManager()

    fake_msg = {
        "payload": {
            "worker_id": "unknown-worker",
            "timestamp": time.time(),
            "nonce": "abc123",
        },
        "signature": "fakesig",
    }
    valid, reason = auth.verify_message(fake_msg)
    assert valid is False
    assert "Unknown" in reason

def test_auth_manager_permission_checks():
    import sys; sys.path.insert(0, "/home/claude/arb-engine-v2")
    from brain.security.auth_manager import AuthManager
    auth = AuthManager()
    auth.register_worker(
        "w-exec-01", "binance", ["BTC/USDT"],
        can_execute_orders=True, max_order_size_usd=5000.0,
    )
    auth.register_worker("w-coll-01", "binance", ["ETH/USDT"], can_execute_orders=False)

    can, _ = auth.can_execute_order("w-exec-01", order_size_usd=4000.0)
    assert can is True

    can, reason = auth.can_execute_order("w-exec-01", order_size_usd=6000.0)
    assert can is False
    assert "exceeds" in reason

    can, reason = auth.can_execute_order("w-coll-01")
    assert can is False
    assert "authorized" in reason

def test_auth_manager_revoke():
    import sys; sys.path.insert(0, "/home/claude/arb-engine-v2")
    from brain.security.auth_manager import AuthManager
    auth = AuthManager()
    secret = auth.register_worker("w-rev-01", "bybit", [])

    auth.revoke_worker("w-rev-01")
    msg = auth.sign_message({"worker_id": "w-rev-01"}, secret)
    valid, reason = auth.verify_message(msg)
    assert valid is False
    assert "revoked" in reason.lower()

# ─── Fleet Monitor ────────────────────────────────────────────────────────────

def test_fleet_worker_state_dead_detection():
    import sys; sys.path.insert(0, "/home/claude/arb-engine-v2")
    from brain.fleet.monitor import WorkerState
    from messaging.models import WorkerStatus, WorkerCondition

    w = WorkerState(
        worker_id="w-dead", exchange="binance",
        pairs=["BTC/USDT"], machine="10.0.0.1",
    )
    w.last_heartbeat = time.time() - 30   # 30 seconds ago

    assert w.is_dead(ttl=15) is True
    assert w.is_dead(ttl=60) is False

def test_fleet_error_classification():
    import sys; sys.path.insert(0, "/home/claude/arb-engine-v2")
    from brain.fleet.monitor import _classify_error
    from messaging.models import WorkerCondition

    assert _classify_error("403 Forbidden") == WorkerCondition.IP_BLOCK
    assert _classify_error("418 I'm a teapot") == WorkerCondition.IP_BLOCK
    assert _classify_error("429 Too Many Requests") == WorkerCondition.RATE_LIMIT
    assert _classify_error("503 Service Unavailable") == WorkerCondition.EXCHANGE_DOWN
    assert _classify_error("401 Unauthorized") == WorkerCondition.AUTH_ERROR
    assert _classify_error("Connection timeout") == WorkerCondition.NONE
    assert _classify_error(None) == WorkerCondition.NONE

# ─── CR 9AM Plugin ───────────────────────────────────────────────────────────

def test_cr_range_builder_htf():
    import sys; sys.path.insert(0, "/home/claude/arb-engine-v2")
    from analysis.plugins.cr_9am.cr_plugin import RangeBuilder
    import pytz

    builder = RangeBuilder("America/New_York")
    ny_tz = pytz.timezone("America/New_York")

    # Build a mock 8AM candle
    eight_am = datetime.now(ny_tz).replace(hour=8, minute=0, second=0, microsecond=0)
    candles_1h = [
        {"time": eight_am, "open": 64800, "high": 65500, "low": 64700, "close": 65200, "volume": 100},
        {"time": eight_am.replace(hour=9), "open": 65200, "high": 65800, "low": 65100, "close": 65600, "volume": 80},
    ]

    htf = builder.build_htf(candles_1h)
    assert htf is not None
    assert htf.high == 65500
    assert htf.low  == 64700
    assert htf.timeframe == "1H"
    assert htf.equilibrium == pytest.approx(65100.0)

def test_cr_range_builder_ltf():
    import sys; sys.path.insert(0, "/home/claude/arb-engine-v2")
    from analysis.plugins.cr_9am.cr_plugin import RangeBuilder
    import pytz

    builder = RangeBuilder("America/New_York")
    ny_tz = pytz.timezone("America/New_York")

    nine_am = datetime.now(ny_tz).replace(hour=9, minute=0, second=0, microsecond=0)
    candles_15m = [
        {"time": nine_am, "open": 65200, "high": 65420, "low": 65180, "close": 65300, "volume": 50},
        {"time": nine_am.replace(minute=15), "open": 65300, "high": 65450, "low": 65250, "close": 65400, "volume": 45},
    ]

    ltf = builder.build_ltf(candles_15m)
    assert ltf is not None
    assert ltf.high == 65420
    assert ltf.low  == 65180
    assert ltf.timeframe == "15M"

def test_sweep_detector_low_sweep():
    import sys; sys.path.insert(0, "/home/claude/arb-engine-v2")
    from analysis.plugins.cr_9am.cr_plugin import SweepDetector
    from messaging.models import CRRange

    detector = SweepDetector()
    ltf = CRRange("15M", datetime.utcnow(), high=65420.0, low=65180.0)

    candles = [
        {"time": datetime.utcnow(), "open": 65200, "high": 65300, "low": 65100, "close": 65220},  # low sweep: wick below 65180, closes above
    ]
    # Adjust to trigger sweep
    candles[0]["low"]   = 65150.0   # wick below ltf.low
    candles[0]["close"] = 65200.0   # closes back above ltf.low

    sweep = detector.detect(candles, ltf)
    assert sweep is not None
    assert sweep.direction == "low_sweep"
    assert sweep.sweep_price == 65150.0
    assert sweep.confirmed is True

def test_fvg_detection_bullish():
    import sys; sys.path.insert(0, "/home/claude/arb-engine-v2")
    from analysis.plugins.cr_9am.cr_plugin import StructureDetector
    from messaging.models import Sweep
    from datetime import timedelta

    detector = StructureDetector()
    sweep_time = datetime(2026, 3, 14, 9, 5, 0)
    sweep = Sweep("low_sweep", 65150.0, sweep_time, 65180.0, confirmed=True)

    t = sweep_time
    candles = [
        {"time": t,                          "open": 65200, "high": 65220, "low": 65190, "close": 65210},
        {"time": t + timedelta(minutes=1),   "open": 65215, "high": 65300, "low": 65210, "close": 65290},
        {"time": t + timedelta(minutes=2),   "open": 65290, "high": 65310, "low": 65250, "close": 65300},
    ]

    fvg = detector.detect_fvg(candles, sweep)
    assert fvg is not None
    assert fvg.direction == "bullish_fvg"
    assert fvg.bottom == 65220.0
    assert fvg.top    == 65250.0
    assert fvg.confirmed is True

def test_entry_validator_produces_long_setup():
    import sys; sys.path.insert(0, "/home/claude/arb-engine-v2")
    from analysis.plugins.cr_9am.cr_plugin import EntryValidator
    from messaging.models import CRRange, FVG, OrderBlock, Sweep

    validator = EntryValidator()
    htf   = CRRange("1H",  datetime.utcnow(), high=66000.0, low=64000.0)
    ltf   = CRRange("15M", datetime.utcnow(), high=65500.0, low=65000.0)
    sweep = Sweep("low_sweep", 64950.0, datetime.utcnow(), 65000.0, confirmed=True)
    ob    = OrderBlock("bullish_ob", 65080.0, 65020.0, 65020.0, 65080.0, datetime.utcnow())
    fvg   = FVG("bullish_fvg", 65120.0, 65090.0, datetime.utcnow(), confirmed=True)

    result = validator.validate(
        sweep, htf, ltf,
        bos=True, ob=ob, fvg=fvg,
        current_price=65200.0,   # price is in discount (below equilibrium 65250)
    )

    assert result is not None
    assert result["direction"] == "long"
    assert result["tp1"] == 65500.0   # opposite end of LTF range
    assert result["tp2"] == 66000.0   # opposite end of HTF range
    assert result["stop_loss"] < 65000.0
    assert result["setup_score"] >= 0.55
    assert result["bos_confirmed"] is True

# ─── Context Engine ───────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_context_engine_auto_creates_context():
    import sys; sys.path.insert(0, "/home/claude/arb-engine-v2")
    from analysis.context_engine import ContextEngine

    engine = ContextEngine(analysis_config={
        "plugins": {"rsi": {"enabled": False}},
    })

    # Feed enough ticks to trigger analysis
    for i in range(50):
        await engine.on_price_tick("binance", "BTC/USDT", 65000.0 + i * 10)

    contexts = engine.get_all_contexts()
    assert len(contexts) == 1
    assert contexts[0]["exchange"] == "binance"
    assert contexts[0]["pair"]     == "BTC/USDT"
    assert contexts[0]["tick_count"] == 50

@pytest.mark.asyncio
async def test_context_engine_multiple_contexts():
    import sys; sys.path.insert(0, "/home/claude/arb-engine-v2")
    from analysis.context_engine import ContextEngine

    engine = ContextEngine(analysis_config={"plugins": {}})

    pairs = [("binance", "BTC/USDT"), ("kraken", "ETH/USDT"), ("uniswap", "ETH/USDT")]
    for exchange, pair in pairs:
        for i in range(35):
            await engine.on_price_tick(exchange, pair, 100.0 + i)

    contexts = engine.get_all_contexts()
    assert len(contexts) == 3

    keys = {c["key"] for c in contexts}
    assert "binance:BTC/USDT" in keys
    assert "kraken:ETH/USDT"  in keys
    assert "uniswap:ETH/USDT" in keys
