#!/usr/bin/env bash
# ARBX Quick Diagnostic — runs in seconds, no Python needed
# Usage:  bash scripts/test_quick.sh [PORT]
set -uo pipefail

PORT="${1:-}"
RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'
CYAN='\033[0;36m'; BOLD='\033[1m'; DIM='\033[2m'; NC='\033[0m'

ok()   { echo -e "  ${GREEN}✓${NC} $1"; }
fail() { echo -e "  ${RED}✗${NC} $1"; FAILS=$((FAILS+1)); }
warn() { echo -e "  ${YELLOW}⚠${NC} $1"; }
info() { echo -e "  ${DIM}  $1${NC}"; }
sep()  { echo -e "${DIM}──────────────────────────────────────────────${NC}"; }

FAILS=0

# ── Auto-detect port ──────────────────────────────────────────────────────────
if [ -z "$PORT" ]; then
  for p in 8005 8000 8080; do
    if curl -sf "http://localhost:$p/api/health" >/dev/null 2>&1; then
      PORT=$p; break
    fi
  done
  PORT="${PORT:-8005}"
fi
BASE="http://localhost:$PORT"

echo -e "\n${BOLD}ARBX Quick Diagnostic${NC}  ${DIM}$(date '+%Y-%m-%d %H:%M:%S')${NC}"
echo -e "${DIM}Target: $BASE${NC}\n"

# ── 0. Docker containers ──────────────────────────────────────────────────────
echo -e "${CYAN}${BOLD}0 · Docker Containers${NC}"
sep
for svc in arb-brain arb-redis arb-postgres arb-worker-manager arb-frontend; do
  if docker ps --format '{{.Names}}' 2>/dev/null | grep -q "^${svc}$"; then
    STATUS=$(docker ps --format '{{.Names}}\t{{.Status}}' | grep "^${svc}" | awk '{$1=""; print $0}' | xargs)
    ok "$svc  ${DIM}$STATUS${NC}"
  else
    fail "$svc not running"
  fi
done

# ── 1. API health ─────────────────────────────────────────────────────────────
echo -e "\n${CYAN}${BOLD}1 · API Health${NC}"
sep
HEALTH=$(curl -sf "$BASE/api/health" 2>/dev/null) || HEALTH=""
if [ -n "$HEALTH" ]; then
  ok "Brain API responding  ${DIM}$HEALTH${NC}"
else
  fail "Brain API not responding at $BASE"
  echo -e "\n${RED}Cannot reach brain. Stopping early.${NC}"
  echo -e "Try: ${YELLOW}make docker-logs${NC} or ${YELLOW}docker logs arb-brain 2>&1 | tail -30${NC}\n"
  exit 1
fi

STATUS=$(curl -sf "$BASE/api/system/status" 2>/dev/null) || STATUS=""
if [ -n "$STATUS" ]; then
  VERSION=$(echo "$STATUS" | python3 -c "import sys,json; d=json.load(sys.stdin); print(d.get('version','?'))" 2>/dev/null)
  MODE=$(echo "$STATUS"    | python3 -c "import sys,json; d=json.load(sys.stdin); print(d.get('trading_mode','?'))" 2>/dev/null)
  WORKERS=$(echo "$STATUS" | python3 -c "import sys,json; d=json.load(sys.stdin); print(d.get('workers',0))" 2>/dev/null)
  ok "Version: $VERSION   Mode: $MODE   Workers: $WORKERS"
else
  fail "System status endpoint returned empty"
fi

# ── 2. Redis ──────────────────────────────────────────────────────────────────
echo -e "\n${CYAN}${BOLD}2 · Redis Streams${NC}"
sep
HB_LEN=$(docker exec arb-redis redis-cli XLEN stream:heartbeats 2>/dev/null || echo "0")
if [ "${HB_LEN:-0}" -gt "0" ] 2>/dev/null; then
  ok "stream:heartbeats has $HB_LEN messages"
else
  warn "stream:heartbeats empty — workers not sending heartbeats yet"
fi

GROUPS=$(docker exec arb-redis redis-cli XINFO GROUPS stream:heartbeats 2>/dev/null || echo "")
if echo "$GROUPS" | grep -q "fleet_monitor" 2>/dev/null; then
  ok "fleet_monitor consumer group exists"
else
  warn "fleet_monitor group not found — brain may still be starting"
fi

for stream in stream:prices stream:orders stream:order_results; do
  LEN=$(docker exec arb-redis redis-cli XLEN "$stream" 2>/dev/null || echo "?")
  info "$stream: $LEN messages"
done

# ── 3. Fleet / Workers ────────────────────────────────────────────────────────
echo -e "\n${CYAN}${BOLD}3 · Fleet Workers${NC}"
sep
FLEET=$(curl -sf "$BASE/api/fleet/workers" 2>/dev/null) || FLEET=""
if [ -n "$FLEET" ]; then
  COUNT=$(echo "$FLEET" | python3 -c "import sys,json; d=json.load(sys.stdin); print(d.get('count',0))" 2>/dev/null)
  if [ "${COUNT:-0}" -gt "0" ] 2>/dev/null; then
    ok "$COUNT worker(s) registered"
    echo "$FLEET" | python3 -c "
import sys, json
d = json.load(sys.stdin)
for w in d.get('workers', []):
    s = w.get('status','?')
    e = w.get('exchange','?')
    pc = w.get('pair_count', len(w.get('pairs',[])))
    sym = '✓' if s=='healthy' else '⚠'
    print(f'      {sym} {e} [{s}] pairs={pc} latency={w.get(\"latency_ms\",0):.1f}ms')
" 2>/dev/null
  else
    fail "0 workers registered (expected > 0 after ~30s)"
    info "Check: docker logs arb-worker-manager 2>&1 | tail -20"
    info "Check: docker logs arb-brain 2>&1 | grep -i 'spawn\|auto'"
  fi
else
  fail "Fleet workers endpoint empty"
fi

# ── 4. Market data ────────────────────────────────────────────────────────────
echo -e "\n${CYAN}${BOLD}4 · Market Data${NC}"
sep
PRICES=$(curl -sf "$BASE/api/market/prices" 2>/dev/null) || PRICES=""
if [ -n "$PRICES" ]; then
  PAIRS=$(echo "$PRICES" | python3 -c "import sys,json; d=json.load(sys.stdin); print(len(d.get('pairs',[])))" 2>/dev/null)
  ok "Prices tracking $PAIRS pairs"
else
  warn "No price data yet"
fi

SPREADS=$(curl -sf "$BASE/api/market/spreads" 2>/dev/null) || SPREADS=""
if [ -n "$SPREADS" ]; then
  SCOUNT=$(echo "$SPREADS" | python3 -c "import sys,json; d=json.load(sys.stdin); s=d.get('spreads',[]); prof=sum(1 for x in s if x.get('profitable')); print(f'{len(s)} spreads {prof} profitable')" 2>/dev/null)
  ok "Spreads: $SCOUNT (fee-adjusted net profit)"
fi

# ── 5. Graph arbitrage ────────────────────────────────────────────────────────
echo -e "\n${CYAN}${BOLD}5 · Graph Arbitrage${NC}"
sep
GSTATE=$(curl -sf "$BASE/api/graph/state" 2>/dev/null) || GSTATE=""
if [ -n "$GSTATE" ]; then
  EDGES=$(echo "$GSTATE" | python3 -c "import sys,json; d=json.load(sys.stdin); print(d.get('edge_count',0))" 2>/dev/null)
  ALGO=$(echo "$GSTATE"  | python3 -c "import sys,json; d=json.load(sys.stdin); print(d.get('algorithm','?'))" 2>/dev/null)
  ok "Graph: $EDGES edges, algo=$ALGO"
  if [ "${EDGES:-0}" -gt "0" ] 2>/dev/null; then
    GPATHS=$(curl -sf "$BASE/api/graph/paths" 2>/dev/null | python3 -c "import sys,json; d=json.load(sys.stdin); ps=d.get('paths',[]); print(f'{len(ps)} paths found')" 2>/dev/null)
    info "Paths: $GPATHS"
  fi
else
  warn "Graph state not available"
fi

# ── 6. Vault / DB ────────────────────────────────────────────────────────────
echo -e "\n${CYAN}${BOLD}6 · Vault (PostgreSQL)${NC}"
sep
KEYS=$(curl -sf "$BASE/api/vault/apikeys" 2>/dev/null) || KEYS=""
if [ -n "$KEYS" ]; then
  KCOUNT=$(echo "$KEYS" | python3 -c "import sys,json; d=json.load(sys.stdin); print(len(d.get('keys',[])))" 2>/dev/null)
  ok "Vault reachable: $KCOUNT API key(s) stored"
  FEES=$(curl -sf "$BASE/api/vault/fees" 2>/dev/null | python3 -c "import sys,json; d=json.load(sys.stdin); print(len(d.get('fees',[])))" 2>/dev/null)
  info "Fee table: $FEES exchanges seeded"
else
  fail "Vault not reachable — PostgreSQL may be down"
  info "Check: docker logs arb-postgres 2>&1 | tail -10"
fi

# ── 7. Orders & Positions ────────────────────────────────────────────────────
echo -e "\n${CYAN}${BOLD}7 · Orders & Positions${NC}"
sep
OPEN=$(curl -sf "$BASE/api/orders/open" 2>/dev/null | python3 -c "import sys,json; d=json.load(sys.stdin); print(len(d.get('orders',[])))" 2>/dev/null || echo "?")
CLOSED=$(curl -sf "$BASE/api/positions/closed" 2>/dev/null | python3 -c "import sys,json; d=json.load(sys.stdin); print(len(d.get('positions',[])))" 2>/dev/null || echo "?")
ok "Open orders: $OPEN   Closed positions: $CLOSED"
FIN=$(curl -sf "$BASE/api/financials/summary" 2>/dev/null) || FIN=""
if [ -n "$FIN" ]; then
  PNL=$(echo "$FIN" | python3 -c "import sys,json; d=json.load(sys.stdin); o=d.get('orders',{}); print(f\"P&L \${o.get('total_pnl_usd',0):+.2f} | {o.get('closed',0)} closed | win_rate={o.get('win_rate',0)}%\")" 2>/dev/null)
  info "$PNL"
fi

# ── 8. Alerts ────────────────────────────────────────────────────────────────
echo -e "\n${CYAN}${BOLD}8 · Alerts${NC}"
sep
ALERT=$(curl -sf -X POST "$BASE/api/alerts/test" 2>/dev/null) || ALERT=""
if [ -n "$ALERT" ]; then
  MSG=$(echo "$ALERT" | python3 -c "import sys,json; d=json.load(sys.stdin); print(d.get('message','?'))" 2>/dev/null)
  ok "Alert test endpoint: $MSG"
else
  warn "Alert test endpoint did not respond"
fi

# ── 9. Config persistence ────────────────────────────────────────────────────
echo -e "\n${CYAN}${BOLD}9 · Config${NC}"
sep
CONF=$(curl -sf "$BASE/api/config/current" 2>/dev/null) || CONF=""
if [ -n "$CONF" ]; then
  SECTIONS=$(echo "$CONF" | python3 -c "import sys,json; d=json.load(sys.stdin); print(', '.join(k for k in d.keys() if isinstance(d[k],dict) or k in ('version','trading_mode')))" 2>/dev/null)
  ok "Config current: $SECTIONS"
else
  fail "Config current endpoint empty"
fi

# ── 10. Trading mode ─────────────────────────────────────────────────────────
echo -e "\n${CYAN}${BOLD}10 · Trading Mode${NC}"
sep
TMODE=$(curl -sf "$BASE/api/trading/mode" 2>/dev/null) || TMODE=""
if [ -n "$TMODE" ]; then
  MODE=$(echo "$TMODE" | python3 -c "import sys,json; d=json.load(sys.stdin); print(d.get('mode','?'))" 2>/dev/null)
  ok "Trading mode: $MODE"
  if [ "$MODE" == "live" ]; then
    warn "Currently in LIVE mode — real orders will be placed"
  fi
else
  fail "Trading mode endpoint not responding"
fi

# ── Summary ────────────────────────────────────────────────────────────────────
echo
sep
if [ "$FAILS" -eq 0 ]; then
  echo -e "  ${GREEN}${BOLD}All checks passed${NC}"
else
  echo -e "  ${RED}${BOLD}$FAILS check(s) failed${NC}"
  echo -e "  Run full test suite: ${YELLOW}python3 scripts/test_all.py --port $PORT${NC}"
fi
echo -e "  Full tests:   ${YELLOW}python3 scripts/test_all.py --port $PORT --verbose${NC}"
echo -e "  JSON report:  ${YELLOW}python3 scripts/test_all.py --port $PORT --json report.json${NC}"
echo
exit $FAILS
