#!/usr/bin/env bash
# Game Price Compare — Daily Scrape Pipeline
# Usage: bash run_scrape.sh [--full]
#
# --full  : Scrapes both stores from scratch
# default : Only scrapes Xbox if >24h old, Steam always scrapes
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$SCRIPT_DIR"

source venv/bin/activate

echo "══════════════════════════════════════════════"
echo "  Game Price Compare — Scrape Pipeline"
echo "  $(date '+%Y-%m-%d %H:%M:%S %Z')"
echo "══════════════════════════════════════════════"

# ─── 1. Scrape Xbox Argentina ───
echo ""
echo "[1/3] Scraping Xbox Argentina..."
python scrapers/xbox_scraper.py 20
echo "  ✓ Xbox scrape complete"

# ─── 2. Scrape Steam Argentina ───
echo ""
echo "[2/3] Scraping Steam Argentina..."
python scrapers/steam_scraper.py 15
echo "  ✓ Steam scrape complete"

# ─── 3. Run Matching Engine ───
echo ""
echo "[3/3] Running matching engine..."
python scrapers/matching_engine.py 80
echo "  ✓ Matching complete"

echo ""
echo "══════════════════════════════════════════════"
echo "  Pipeline finished: $(date '+%Y-%m-%d %H:%M:%S %Z')"
echo "══════════════════════════════════════════════"