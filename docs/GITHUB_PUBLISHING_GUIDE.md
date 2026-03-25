# ARBX — GitHub Publishing Guide

> **Document:** Step-by-step guide to publish ARBX v1 and v2 to GitHub  
> **Audience:** Anyone setting up the project repository for the first time  
> **Time required:** ~20 minutes for the full setup

---

## Table of Contents

1. [Prerequisites](#1-prerequisites)
2. [Create the GitHub Repository](#2-create-the-github-repository)
3. [Publish v1 — main branch](#3-publish-v1--main-branch)
4. [Publish v2 — v2 branch](#4-publish-v2--v2-branch)
5. [Create a GitHub Release for v2](#5-create-a-github-release-for-v2)
6. [Repository Settings & Final Setup](#6-repository-settings--final-setup)
7. [All Commit Messages & Descriptions](#7-all-commit-messages--descriptions)
8. [GitHub Text — Ready to Copy](#8-github-text--ready-to-copy)

---

## 1. Prerequisites

Before starting, make sure you have:

```bash
# Verify Git is installed
git --version
# Expected: git version 2.x.x

# Verify Git is configured with your identity
git config --global user.name
git config --global user.email
```

If Git is not configured:

```bash
git config --global user.name "Your Name"
git config --global user.email "your@email.com"
```

You also need:
- A GitHub account at [github.com](https://github.com)
- Both ZIP files: `arbitrage-engine-complete.zip` (v1) and `arbx-v2-complete.zip` (v2)

### Authentication — choose one method

**Option A: HTTPS with Personal Access Token (recommended for beginners)**

1. Go to GitHub → Settings → Developer settings → Personal access tokens → Tokens (classic)
2. Click "Generate new token"
3. Select scopes: `repo` (full)
4. Copy the token — you will paste it when Git asks for a password

**Option B: SSH key (recommended for regular use)**

```bash
# Generate SSH key
ssh-keygen -t ed25519 -C "your@email.com"
# Press Enter for all prompts

# Copy public key to clipboard
cat ~/.ssh/id_ed25519.pub
# Linux: cat ~/.ssh/id_ed25519.pub | xclip -selection clipboard
# macOS: cat ~/.ssh/id_ed25519.pub | pbcopy

# Add to GitHub: Settings → SSH keys → New SSH key → Paste
```

Test your connection:

```bash
ssh -T git@github.com
# Expected: Hi your-username! You've successfully authenticated...
```

---

## 2. Create the GitHub Repository

> 📊 **Flow diagram:** See the GitHub Publishing Flow diagram generated above.

### Step 1 — Create a new repository on GitHub

1. Go to [github.com/new](https://github.com/new)
2. Fill in the form:

| Field | Value |
|---|---|
| **Repository name** | `arbx` |
| **Description** | *(copy from Section 8.1 below)* |
| **Visibility** | Public or Private — your choice |
| **Initialize repository** | ❌ **Do NOT check this** — you will push existing code |
| **Add .gitignore** | ❌ None |
| **Add license** | Optional — MIT recommended |

3. Click **"Create repository"**

4. GitHub shows you an empty repo page. **Copy the repository URL** — you need it in Step 3:
   - HTTPS: `https://github.com/your-username/arbx.git`
   - SSH: `git@github.com:your-username/arbx.git`

---

## 3. Publish v1 — main branch

### Step 1 — Unzip the v1 project

```bash
# Create a dedicated workspace folder
mkdir ~/arbx-workspace
cd ~/arbx-workspace

# Unzip v1
unzip /path/to/arbitrage-engine-complete.zip

# Verify the contents
ls -la arbitrage-engine-v2/
# Expected: README.md, arbitrage_engine/, frontend/, docker/, config/, etc.
```

> **Note:** The v1 ZIP extracts to a folder named `arbitrage-engine-v2`. Rename it for clarity:

```bash
mv arbitrage-engine-v2 arbx
cd arbx
```

### Step 2 — Initialize the Git repository

```bash
# Initialize Git in the project folder
git init

# Verify you are in the right folder
ls
# Expected: README.md, Makefile, requirements.txt, arbitrage_engine/, frontend/, etc.
```

### Step 3 — Create .gitignore (if not already present)

```bash
# Check if .gitignore exists
ls -la | grep gitignore

# If it exists, you are fine. If not, create it:
cat > .gitignore << 'EOF'
# Secrets
config/.env
*.env.secret
config/certs/*.key

# Python
__pycache__/
*.pyc
.pytest_cache/
.venv/
venv/

# Node
frontend/node_modules/
frontend/dist/

# OS
.DS_Store
Thumbs.db
EOF
```

### Step 4 — Verify no secrets are staged

```bash
# Check that .env is not being tracked
cat config/.env.example   # This is safe to commit — it has no real values
ls config/                # Should NOT see a plain .env file (only .env.example)
```

If `config/.env` exists with real values, it must be excluded:

```bash
# Ensure .gitignore is protecting it
echo "config/.env" >> .gitignore
git check-ignore -v config/.env   # Should output: .gitignore:X:config/.env
```

### Step 5 — Stage all files

```bash
# Add all files to staging
git add .

# Review what is staged — take 30 seconds to check this
git status
```

Expected output (abbreviated):

```
Changes to be committed:
  new file:   .gitignore
  new file:   Makefile
  new file:   README.md
  new file:   arbitrage_engine/__init__.py
  new file:   arbitrage_engine/engine.py
  new file:   arbitrage_engine/scheduler/scheduler.py
  ... (many more files)
  new file:   config/config.yaml
  new file:   config/.env.example   ← this is safe
  new file:   frontend/index.html
  new file:   requirements.txt
  new file:   tests/test_batch_a.py
  new file:   tests/test_batch_b.py
  new file:   tests/test_batch_c.py
```

**Verify these are NOT in the list:**
- `config/.env` ← must NOT be staged
- `*.env.secret` ← must NOT be staged
- Any file containing real API keys

### Step 6 — Make the initial commit

```bash
git commit -m "feat: initial ARBX v1 release

ARBX — Distributed Arbitrage Intelligence Platform

Version 1.0.0 — Monolithic architecture baseline.

Features:
- 7 arbitrage strategies (spatial, triangular, DEX, cross-chain,
  flash loan simulation, FX, multi-country)
- Hybrid market data collectors (CCXT + web3.py + forex)
- CEX: Binance, Kraken, Coinbase, Bybit
- DEX: Uniswap, SushiSwap, PancakeSwap, Curve
- Redis opportunity cache with TTL deduplication
- PostgreSQL persistence (prices, opportunities, trades, FX rates)
- Opportunity ranking engine (6-factor weighted scoring)
- Dry-run trading simulator (fees, slippage, gas)
- Balance manager and rebalancing suggestions
- Market analysis: RSI, MACD, Bollinger Bands, AR(1) prediction
- Pattern detection: support/resistance, double top/bottom
- Sentiment analysis: Fear & Greed Index integration
- Alert system: console, ntfy, email, webhook, Slack
- Prometheus metrics (9 metric types)
- FastAPI REST API (9 routes + WebSocket)
- React + Vite dashboard (6 panels)
- Docker Compose deployment (6 services)
- 40 tests, all passing

Dry-run mode enabled by default.
No real trades execute without explicit configuration."
```

### Step 7 — Connect to GitHub and push

```bash
# Connect your local repo to GitHub
# Replace YOUR-USERNAME with your actual GitHub username

# If using HTTPS:
git remote add origin https://github.com/YOUR-USERNAME/arbx.git

# If using SSH:
git remote add origin git@github.com:YOUR-USERNAME/arbx.git

# Verify the remote was added
git remote -v
# Expected:
# origin  https://github.com/YOUR-USERNAME/arbx.git (fetch)
# origin  https://github.com/YOUR-USERNAME/arbx.git (push)

# Set the default branch name to "main"
git branch -M main

# Push to GitHub
git push -u origin main
```

If using HTTPS, Git will ask for your username and password — use your GitHub username and the Personal Access Token as the password.

### Step 8 — Verify v1 is on GitHub

1. Open `https://github.com/YOUR-USERNAME/arbx`
2. You should see all files listed
3. The README.md should render at the bottom of the page
4. Repository shows `1 branch: main`

**Tag v1 for reference:**

```bash
git tag -a v1.0.0 -m "ARBX v1.0.0 — Monolithic baseline

Initial release. Single-process architecture.
All collectors, strategies, and analysis in one engine.
See README.md for full feature list."

git push origin v1.0.0
```

---

## 4. Publish v2 — v2 branch

> 📊 **Flow diagram:** See the GitHub Publishing Flow diagram — the lower half shows the v2 branch workflow.

### Step 1 — Create the v2 branch

You must be in the `arbx` folder from Step 3 above.

```bash
# Ensure you are on main and up to date
git checkout main
git status      # Should say: nothing to commit, working tree clean

# Create and switch to the v2 branch
git checkout -b v2

# Verify you are on the new branch
git branch
# Expected:
#   main
# * v2    ← asterisk shows current branch
```

### Step 2 — Unzip the v2 project into a temporary folder

Open a **second terminal** for this (keep the first one in the `arbx` folder):

```bash
# Second terminal
cd ~/arbx-workspace

# Unzip v2 to a temporary location
mkdir v2-temp
unzip /path/to/arbx-v2-complete.zip -d v2-temp

# See what was extracted
ls v2-temp/
# Expected: arb-engine-v2/
```

### Step 3 — Copy v2 files into the repository

Back in your **first terminal** (inside the `arbx` folder, on the `v2` branch):

```bash
# Copy all v2 files into the repo, overwriting v1 files
cp -r ~/arbx-workspace/v2-temp/arb-engine-v2/* .

# Verify key new files are present
ls brain/          # Should exist
ls worker/         # Should exist
ls messaging/      # Should exist
ls analysis/plugins/cr_9am/   # Should exist

# Clean up temp folder
rm -rf ~/arbx-workspace/v2-temp
```

### Step 4 — Review what changed

```bash
git status
```

You will see a long list of changes. Key things to verify:

```
Changes not staged for commit:
  modified:   README.md          ← now contains ARBX branding
  modified:   config/config.yaml ← new v2 structure
  modified:   requirements.txt   ← new dependencies (pytz)
  modified:   Makefile           ← new commands

New files:
  brain/brain.py
  brain/security/auth_manager.py
  brain/fleet/monitor.py
  brain/stream/subscriber.py
  worker/worker.py
  worker_manager/manager.py
  messaging/bus.py
  messaging/models.py
  analysis/context_engine.py
  analysis/plugins/registry.py
  analysis/plugins/cr_9am/cr_plugin.py
  storage/market_state.py
  api/routes/fleet.py
  api/routes/cr_signals.py
  api/routes/security.py
  api/routes/websocket.py
  frontend/src/components/FleetHealth.jsx
  frontend/src/components/CRPanel.jsx
  frontend/src/components/SecurityPanel.jsx
  docs/INSTALL_DEPLOY_MAINTAIN.md
  docs/SYSTEM_DESCRIPTION.md
  docs/V1_TO_V2_RELEASE_NOTES.md
  docs/GITHUB_README_HEADER.md
  ... (many more)
```

**One more secret check:**

```bash
git status | grep "\.env$"     # Should show nothing — .env must not appear
git status | grep "secret"     # Should show nothing
```

### Step 5 — Stage all v2 changes

```bash
git add .

# Final review of what is staged
git status | head -60
```

### Step 6 — Commit v2

```bash
git commit -m "feat: v2.0.0 distributed worker architecture

ARBX v2.0.0 — Major architectural overhaul.

BREAKING: Brain no longer connects to exchanges directly.
All market data arrives via Redis Streams from distributed workers.

New capabilities:
- Distributed worker fleet (any machine, any network)
- Redis Streams message bus (12 named streams)
- Fleet health monitor with automatic failover (~9s recovery)
- Per-(exchange × pair) analysis contexts (isolated signal per pair)
- Self-registering analysis plugin system
- 9AM CR Model — full ICT Candle Range Theory implementation
  (8AM HTF range, 9AM LTF range, sweep detection, BOS/OB/FVG)
- Multi-layer security (HMAC-SHA256 + nonce/replay protection)
- Worker credential management with instant revocation
- 10 new API routes + 3 WebSocket live streams
- 9 dashboard panels (Fleet, CR Model, Coverage Map, Security, Events)
- Worker Manager daemon for automatic Docker spawn on failover
- Docker Compose expanded to 10 services

Preserved from v1:
- All 7 arbitrage strategies
- Opportunity scoring and ranking
- Dry-run trading simulator
- Balance manager
- Redis cache + PostgreSQL
- Alert system (all 5 channels)
- Prometheus metrics

Tests: 18 passed.
Dry-run enabled by default.

See docs/V1_TO_V2_RELEASE_NOTES.md for full migration guide."
```

### Step 7 — Push v2 branch to GitHub

```bash
git push -u origin v2
```

### Step 8 — Verify v2 is on GitHub

1. Open `https://github.com/YOUR-USERNAME/arbx`
2. Click the branch dropdown (currently showing `main`)
3. Select `v2`
4. You should see the new files (`brain/`, `worker/`, `messaging/`, etc.)
5. Repository now shows `2 branches: main, v2`

**Tag v2:**

```bash
git tag -a v2.0.0 -m "ARBX v2.0.0 — Distributed Worker Architecture

Major release. See docs/V1_TO_V2_RELEASE_NOTES.md for details.

Key changes:
- Distributed worker fleet with automatic failover
- Per-context analysis engine (per exchange x pair)
- 9AM CR Model (ICT Candle Range Theory)
- Multi-layer security (HMAC + registry + nonce protection)
- 9 dashboard panels

18 tests passing."

git push origin v2.0.0
```

---

## 5. Create a GitHub Release for v2

A GitHub Release creates a downloadable snapshot tied to your tag with formatted release notes.

### Step 1 — Go to Releases

1. Open your repository on GitHub
2. Click **"Releases"** in the right sidebar (or go to `github.com/YOUR-USERNAME/arbx/releases`)
3. Click **"Create a new release"**

### Step 2 — Fill in the release form

| Field | Value |
|---|---|
| **Tag** | Select existing tag: `v2.0.0` |
| **Release title** | `ARBX v2.0.0 — Distributed Worker Architecture` |
| **Description** | *(paste content from `docs/V1_TO_V2_RELEASE_NOTES.md`)* |
| **Set as latest release** | ✅ Yes |
| **Set as pre-release** | ❌ No |

### Step 3 — Attach ZIP files (optional)

In the "Attach binaries" section, you can drag and drop:
- `arbx-v2-complete.zip` — the full source ZIP

### Step 4 — Publish

Click **"Publish release"**.

The release is now visible at `github.com/YOUR-USERNAME/arbx/releases/tag/v2.0.0`.

---

## 6. Repository Settings & Final Setup

### README.md — apply ARBX branding

The file `docs/GITHUB_README_HEADER.md` contains the full branded README. Apply it:

```bash
# On the v2 branch
git checkout v2

# Replace README.md with the branded version
cp docs/GITHUB_README_HEADER.md README.md

# Update the clone URL in README.md to your actual repo
# Open README.md and change:
#   git clone https://github.com/your-org/arbx.git
# To:
#   git clone https://github.com/YOUR-USERNAME/arbx.git
nano README.md      # or your preferred editor

git add README.md
git commit -m "docs: apply ARBX branding to README"
git push origin v2
```

### Repository description on GitHub

1. Open your repository on GitHub
2. Click the ⚙️ gear icon next to "About" (top right of the repo page)
3. Fill in:

**Description:**
```
Distributed Arbitrage Intelligence — Scan Every Market. Miss Nothing.
```

**Website:**
```
http://localhost:3000
```
*(or your actual deployment URL if you have one)*

**Topics (tags):**
```
arbitrage crypto trading python fastapi redis docker react distributed
```

Click **"Save changes"**.

### Branch protection (recommended for teams)

1. Go to Settings → Branches → Add rule
2. Branch name pattern: `main`
3. Enable:
   - ✅ Require pull request reviews before merging
   - ✅ Require status checks to pass (select pytest if you set up CI)
   - ✅ Do not allow bypassing the above settings

### Set default branch

The `main` branch contains v1. The `v2` branch is the current version. Consider making `v2` the default:

1. Settings → General → Default branch
2. Click the switch icon next to `main`
3. Select `v2`
4. Click **"Update"**

---

## 7. All Commit Messages & Descriptions

These are the exact commit messages used at each stage. Copy them precisely.

### v1 initial commit

```
feat: initial ARBX v1 release

ARBX — Distributed Arbitrage Intelligence Platform

Version 1.0.0 — Monolithic architecture baseline.

Features:
- 7 arbitrage strategies (spatial, triangular, DEX, cross-chain,
  flash loan simulation, FX, multi-country)
- Hybrid market data collectors (CCXT + web3.py + forex)
- CEX: Binance, Kraken, Coinbase, Bybit
- DEX: Uniswap, SushiSwap, PancakeSwap, Curve
- Redis opportunity cache with TTL deduplication
- PostgreSQL persistence (prices, opportunities, trades, FX rates)
- Opportunity ranking engine (6-factor weighted scoring)
- Dry-run trading simulator (fees, slippage, gas)
- Balance manager and rebalancing suggestions
- Market analysis: RSI, MACD, Bollinger Bands, AR(1) prediction
- Pattern detection: support/resistance, double top/bottom
- Sentiment analysis: Fear & Greed Index integration
- Alert system: console, ntfy, email, webhook, Slack
- Prometheus metrics (9 metric types)
- FastAPI REST API (9 routes + WebSocket)
- React + Vite dashboard (6 panels)
- Docker Compose deployment (6 services)
- 40 tests, all passing

Dry-run mode enabled by default.
No real trades execute without explicit configuration.
```

### v1 tag message

```
ARBX v1.0.0 — Monolithic baseline

Initial release. Single-process architecture.
All collectors, strategies, and analysis in one engine.
See README.md for full feature list.
```

### v2 main commit

```
feat: v2.0.0 distributed worker architecture

ARBX v2.0.0 — Major architectural overhaul.

BREAKING: Brain no longer connects to exchanges directly.
All market data arrives via Redis Streams from distributed workers.

New capabilities:
- Distributed worker fleet (any machine, any network)
- Redis Streams message bus (12 named streams)
- Fleet health monitor with automatic failover (~9s recovery)
- Per-(exchange × pair) analysis contexts (isolated signal per pair)
- Self-registering analysis plugin system
- 9AM CR Model — full ICT Candle Range Theory implementation
  (8AM HTF range, 9AM LTF range, sweep detection, BOS/OB/FVG)
- Multi-layer security (HMAC-SHA256 + nonce/replay protection)
- Worker credential management with instant revocation
- 10 new API routes + 3 WebSocket live streams
- 9 dashboard panels (Fleet, CR Model, Coverage Map, Security, Events)
- Worker Manager daemon for automatic Docker spawn on failover
- Docker Compose expanded to 10 services

Preserved from v1:
- All 7 arbitrage strategies
- Opportunity scoring and ranking
- Dry-run trading simulator
- Balance manager
- Redis cache + PostgreSQL
- Alert system (all 5 channels)
- Prometheus metrics

Tests: 18 passed.
Dry-run enabled by default.

See docs/V1_TO_V2_RELEASE_NOTES.md for full migration guide.
```

### v2 tag message

```
ARBX v2.0.0 — Distributed Worker Architecture

Major release. See docs/V1_TO_V2_RELEASE_NOTES.md for details.

Key changes:
- Distributed worker fleet with automatic failover
- Per-context analysis engine (per exchange x pair)
- 9AM CR Model (ICT Candle Range Theory)
- Multi-layer security (HMAC + registry + nonce protection)
- 9 dashboard panels

18 tests passing.
```

### README branding commit

```
docs: apply ARBX branding to README

Add ARBX name, tagline, and description.
Update clone URL to actual repository.
Add badge row (version, Python, React, Redis, dry-run, tests).
```

---

## 8. GitHub Text — Ready to Copy

### 8.1 Repository description

```
Distributed Arbitrage Intelligence — Scan Every Market. Miss Nothing.
```

### 8.2 Repository topics

```
arbitrage crypto trading python fastapi redis docker react distributed
```

### 8.3 Release title for v2

```
ARBX v2.0.0 — Distributed Worker Architecture
```

### 8.4 Release description for v2

*(Paste the full content of `docs/V1_TO_V2_RELEASE_NOTES.md`)*

### 8.5 Pull request title (if you use PRs to merge v2 into main)

```
feat: v2.0.0 distributed worker architecture and 9AM CR model
```

### 8.6 Pull request body

```markdown
## ARBX v2.0.0

Major architectural overhaul of the arbitrage engine.

### What changed
- Brain no longer connects to exchanges — workers do
- Redis Streams message bus for all brain↔worker communication
- Automatic fleet failover (IP block, crash, overload)
- Per-(exchange × pair) analysis contexts
- Self-registering analysis plugin system
- **9AM CR Model** — full ICT Candle Range Theory (BOS/OB/FVG)
- Multi-layer worker security (HMAC + nonce + registry)
- 9 dashboard panels (Fleet Health, CR Model, Coverage Map, Security, Events)

### Tests
18/18 passing — `make test`

### Breaking changes
- Entry point changed: `scripts/run_engine.py` → `scripts/run_brain.py`
- Collectors now run as separate worker processes
- Config structure changed (`engine:` → `brain:`, new `analysis.plugins` structure)

### Migration
See `docs/V1_TO_V2_RELEASE_NOTES.md` for step-by-step migration guide.

### Checklist
- [x] Tests passing (18/18)
- [x] Dry-run mode verified
- [x] Documentation updated
- [x] Release notes written
- [x] Breaking changes documented
```

---

## Quick Reference Card

```
┌────────────────────────────────────────────────────────────┐
│                  ARBX GitHub Workflow                      │
├────────────────────────────────────────────────────────────┤
│                                                            │
│  Unzip v1          unzip arbx-v1.zip && cd arbx           │
│  Init git          git init                                │
│  Stage             git add .                               │
│  Commit v1         git commit -m "feat: initial ARBX v1"  │
│  Add remote        git remote add origin <github-url>      │
│  Push main         git push -u origin main                 │
│  Tag v1            git tag -a v1.0.0 && git push v1.0.0   │
│                                                            │
│  ─────────────────────────────────────────────────────     │
│                                                            │
│  New branch        git checkout -b v2                      │
│  Copy v2 files     cp -r v2-temp/arb-engine-v2/* .        │
│  Stage             git add .                               │
│  Commit v2         git commit -m "feat: v2.0.0 ..."        │
│  Push v2           git push -u origin v2                   │
│  Tag v2            git tag -a v2.0.0 && git push v2.0.0   │
│                                                            │
│  Create Release    github.com/user/arbx/releases/new       │
│                                                            │
└────────────────────────────────────────────────────────────┘
```

---

*ARBX v2.0.0 — Distributed Arbitrage Intelligence*
