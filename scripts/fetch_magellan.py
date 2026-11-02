#!/usr/bin/env python3
"""
fetch_magellan.py
-----------------
Standalone script to fetch analytics snapshot from Russian Magellan PRO
and save to data/magellan_cache.json for offline fallback on Streamlit Cloud.
Can be executed locally or via GitHub Actions schedule.
"""
from datetime import datetime, timezone, timedelta
import json
import logging
from pathlib import Path
import sys

# Ensure repository root is in python path
ROOT_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT_DIR))

from src.magellan_gateway import MagellanGateway, BANK_REGNUM_MAP

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("fetch_magellan")

CACHE_PATH = ROOT_DIR / "data" / "magellan_cache.json"


def fetch_all_and_cache():
    logger.info("Connecting to Russian Magellan PRO...")
    gw = MagellanGateway(timeout=10)
    
    cache_data = {}
    if CACHE_PATH.exists():
        try:
            with open(CACHE_PATH, "r", encoding="utf-8") as f:
                cache_data = json.load(f)
        except Exception:
            cache_data = {}

    msk_now = datetime.now(timezone(timedelta(hours=3))).strftime("%Y-%m-%d %H:%M:%S МСК")
    cache_data["updated_at"] = msk_now

    # 1. Order Flow
    logger.info("Fetching Order Flow (today & week)...")
    of_today = gw.get_order_flow("today")
    if of_today:
        cache_data["order_flow_today"] = of_today
        logger.info("Order Flow today: %d items", len(of_today))
        
    of_week = gw.get_order_flow("week")
    if of_week:
        cache_data["order_flow_week"] = of_week
        logger.info("Order Flow week: %d items", len(of_week))

    # 2. Banks Summary
    logger.info("Fetching Banks summary (RSBU)...")
    banks = gw.get_banks_summary()
    if banks:
        cache_data["banks_summary"] = banks
        logger.info("Banks summary: %d banks", len(banks))

    # 3. Bank Details
    logger.info("Fetching Bank details...")
    bank_details = cache_data.get("bank_details", {})
    for ticker in BANK_REGNUM_MAP:
        det = gw.get_bank_details(ticker)
        if det:
            bank_details[ticker] = det
            logger.info("Bank details for %s: OK", ticker)
    cache_data["bank_details"] = bank_details

    # 4. Bonds Stress Radar
    logger.info("Fetching Bonds Stress Radar...")
    bonds = gw.get_bonds_stress_radar()
    if bonds:
        cache_data["bonds_stress_radar"] = bonds
        logger.info("Bonds stress radar: %d issuers", len(bonds))

    # 5. Funds Rebalancing
    logger.info("Fetching Funds Rebalancing...")
    funds = gw.get_funds_rebalancing()
    if funds:
        cache_data["funds_rebalancing"] = funds
    elif "funds_rebalancing" not in cache_data:
        cache_data["funds_rebalancing"] = {}

    # 6. IPR Summary
    logger.info("Fetching IPR Summary...")
    ipr = gw.get_ipr_summary()
    if ipr:
        cache_data["ipr_summary"] = ipr
        logger.info("IPR summary: %d companies", len(ipr))

    CACHE_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(CACHE_PATH, "w", encoding="utf-8") as f:
        json.dump(cache_data, f, ensure_ascii=False, indent=2)

    logger.info("Successfully updated Magellan cache at %s (size: %.1f KB)", CACHE_PATH, CACHE_PATH.stat().st_size / 1024)


if __name__ == "__main__":
    fetch_all_and_cache()
