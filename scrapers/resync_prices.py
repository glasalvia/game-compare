#!/usr/bin/env python3
"""
Price Resync — Actualiza precios de juegos existentes sin re-hacer matching IGDB.

Steam: appdetails API por juego (~3 req/s, ~2 min para 341 juegos)
Xbox: Display Catalog API en batches de 100 (~3 reqs para 277 juegos, <3 seg)

Uso:
  python scrapers/resync_prices.py              # Todos los juegos
  python scrapers/resync_prices.py --steam      # Solo Steam
  python scrapers/resync_prices.py --xbox       # Solo Xbox
  python scrapers/resync_prices.py --comparable # Solo juegos en igdb_steam_to_xbox
  python scrapers/resync_prices.py --dry-run    # Simular sin escribir
"""
import argparse
import sqlite3
import time
import requests
import sys
from datetime import datetime, timezone
from pathlib import Path

DB_PATH = str(Path(__file__).resolve().parent.parent / "data" / "games.db")
STEAM_API = "https://store.steampowered.com/api/appdetails"
DISPLAY_CATALOG_API = "https://displaycatalog.mp.microsoft.com/v7.0/products"

STEAM_DELAY = 0.35
XBOX_DELAY = 0.5
XBOX_BATCH = 100
MAX_RETRIES = 2
PRICE_TOLERANCE_PCT = 1.0


def query_steam_price(app_id):
    for attempt in range(MAX_RETRIES):
        try:
            resp = requests.get(STEAM_API, params={
                "appids": app_id, "cc": "ar"
            }, timeout=15)
            resp.raise_for_status()
            data = resp.json().get(str(app_id), {})
            if not data.get("success"):
                return None
            price_data = data.get("data", {}).get("price_overview", {})
            is_free = data.get("data", {}).get("is_free", False)
            if not price_data and is_free:
                return {"price": 0, "original_price": 0, "discount_pct": 0, "is_free": True}
            if not price_data:
                return None
            return {
                "price": price_data.get("final", 0) / 100.0,
                "original_price": price_data.get("initial", 0) / 100.0,
                "discount_pct": price_data.get("discount_percent", 0),
                "is_free": False,
            }
        except Exception:
            if attempt < MAX_RETRIES - 1:
                time.sleep(1)
    return None


def query_xbox_prices(big_ids):
    url = (
        f"{DISPLAY_CATALOG_API}"
        f"?bigIds={','.join(big_ids)}"
        f"&market=AR"
        f"&languages=es-ar"
        f"&actionFilter=Purchase"
    )
    for attempt in range(MAX_RETRIES):
        try:
            resp = requests.get(url, timeout=30)
            resp.raise_for_status()
            products = resp.json().get("Products", [])
            results = {}
            for p in products:
                pid = p.get("ProductId")
                price_data = None
                is_free = False
                availabilities = p.get("DisplaySkuAvailabilities", [])
                for sku in availabilities:
                    for avail in sku.get("Availabilities", []):
                        price_obj = avail.get("OrderManagementData", {}).get("Price", {})
                        if price_obj:
                            price_data = price_obj
                            break
                    if price_data:
                        break
                if price_data:
                    results[pid] = {
                        "price": price_data.get("ListPrice", 0) or 0,
                        "msrp": price_data.get("MSRP", 0) or 0,
                        "wholesale": price_data.get("WholesalePrice"),
                        "currency": price_data.get("CurrencyCode", "ARS"),
                        "is_free": bool(price_data.get("IsFree", False)),
                    }
                elif is_free:
                    results[pid] = {"price": 0, "msrp": 0, "wholesale": 0, "currency": "ARS", "is_free": True}
            return results
        except Exception:
            if attempt < MAX_RETRIES - 1:
                time.sleep(1)
    return {}


def price_changed(old_price, new_price):
    if old_price is None:
        return True
    if new_price is None:
        return False
    if old_price == 0 and new_price == 0:
        return False
    if old_price == 0 or new_price == 0:
        return True
    pct = abs(new_price - old_price) / old_price * 100
    return pct > PRICE_TOLERANCE_PCT


def resync_steam(conn, dry_run=False):
    rows = conn.execute("""
        SELECT g.id, g.store_game_id as app_id, g.title,
               p.price, p.original_price, p.discount_percent, p.is_free
        FROM games g
        JOIN prices p ON p.game_id = g.id
        WHERE g.store_id = 2
        ORDER BY g.id
    """).fetchall()

    total = len(rows)
    updated = 0
    unchanged = 0
    api_fail = 0

    print(f"\n─── STEAM ({total} juegos) ───")

    for i, r in enumerate(rows):
        time.sleep(STEAM_DELAY)
        new_data = query_steam_price(r["app_id"])

        if new_data is None:
            api_fail += 1
            if i % 50 == 0:
                print(f"  [{i+1}/{total}] {(i+1)/total*100:.0f}% | ↻ {updated} | ✓ {unchanged} | ✗ {api_fail}")
            continue

        changed_price = price_changed(r["price"], new_data["price"])
        changed_is_free = r["is_free"] != new_data["is_free"]

        if changed_price or changed_is_free:
            if not dry_run:
                conn.execute("""
                    UPDATE prices SET
                        price = ?,
                        original_price = ?,
                        discount_percent = ?,
                        is_free = ?,
                        scraped_at = CURRENT_TIMESTAMP,
                        price_verified = 1,
                        verified_at = CURRENT_TIMESTAMP,
                        verified_source = 'resync'
                    WHERE game_id = ?
                """, (
                    new_data["price"], new_data["original_price"],
                    new_data["discount_pct"], int(new_data["is_free"]),
                    r["id"]
                ))
                conn.execute("""
                    UPDATE igdb_steam_to_xbox SET
                        steam_price_usd = ?,
                        steam_original_usd = ?,
                        steam_discount_pct = ?,
                        steam_is_free = ?
                    WHERE steam_app_id = ?
                """, (
                    new_data["price"], new_data["original_price"],
                    new_data["discount_pct"], int(new_data["is_free"]),
                    r["app_id"]
                ))
            updated += 1
        else:
            unchanged += 1

        if i % 50 == 0:
            status = "DRY-RUN " if dry_run else ""
            print(f"  [{i+1}/{total}] {(i+1)/total*100:.0f}% | ↻ {updated} | ✓ {unchanged} | ✗ {api_fail}")

        if i % 25 == 0 and not dry_run:
            conn.commit()

    if not dry_run:
        conn.commit()

    print(f"  FINAL: {updated} actualizados | {unchanged} sin cambio | {api_fail} fallos API")


def resync_xbox(conn, dry_run=False):
    rows = conn.execute("""
        SELECT g.id, g.store_game_id as product_id, g.title,
               p.price, p.original_price, p.is_free
        FROM games g
        JOIN prices p ON p.game_id = g.id
        WHERE g.store_id = 1
        ORDER BY g.id
    """).fetchall()

    total = len(rows)
    updated = 0
    unchanged = 0
    not_found = 0

    print(f"\n─── XBOX ({total} juegos) ───")

    for batch_start in range(0, total, XBOX_BATCH):
        batch = rows[batch_start:batch_start + XBOX_BATCH]
        batch_ids = [r["product_id"] for r in batch]

        time.sleep(XBOX_DELAY)
        results = query_xbox_prices(batch_ids)

        for r in batch:
            new_data = results.get(r["product_id"])
            if new_data is None:
                not_found += 1
                continue

            changed_price = price_changed(r["price"], new_data["price"])
            changed_is_free = r["is_free"] != new_data["is_free"]

            if changed_price or changed_is_free:
                if not dry_run:
                    conn.execute("""
                        UPDATE prices SET
                            price = ?,
                            original_price = ?,
                            is_free = ?,
                            scraped_at = CURRENT_TIMESTAMP,
                            price_verified = 1,
                            verified_at = CURRENT_TIMESTAMP,
                            verified_source = 'resync'
                        WHERE game_id = ?
                    """, (
                        new_data["price"], new_data["msrp"],
                        int(new_data["is_free"]), r["id"]
                    ))
                    conn.execute("""
                        UPDATE igdb_steam_to_xbox SET
                            xbox_price_ars = ?,
                            xbox_msrp_ars = ?,
                            xbox_wholesale_ars = ?,
                            xbox_is_free = ?
                        WHERE xbox_store_id = ?
                    """, (
                        new_data["price"], new_data["msrp"],
                        new_data["wholesale"], int(new_data["is_free"]),
                        r["product_id"]
                    ))
                updated += 1
            else:
                unchanged += 1

        batch_num = batch_start // XBOX_BATCH + 1
        total_batches = (total + XBOX_BATCH - 1) // XBOX_BATCH
        status = "DRY-RUN " if dry_run else ""
        print(f"  [batch {batch_num}/{total_batches}] {min(batch_start+XBOX_BATCH, total)}/{total} | ↻ {updated} | ✓ {unchanged} | ? {not_found}")

        if not dry_run:
            conn.commit()

    print(f"  FINAL: {updated} actualizados | {unchanged} sin cambio | {not_found} no encontrados")


def main():
    parser = argparse.ArgumentParser(description="Re-sync de precios Steam + Xbox")
    parser.add_argument("--steam", action="store_true", help="Solo Steam")
    parser.add_argument("--xbox", action="store_true", help="Solo Xbox")
    parser.add_argument("--comparable", action="store_true", help="Solo juegos en igdb_steam_to_xbox")
    parser.add_argument("--dry-run", action="store_true", help="Simular sin escribir cambios")
    args = parser.parse_args()

    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row

    mode = "DRY-RUN" if args.dry_run else "RESYNC"
    if args.steam:
        target = "Steam"
    elif args.xbox:
        target = "Xbox"
    elif args.comparable:
        target = "Comparables (igdb_steam_to_xbox)"
    else:
        target = "Completo"

    print(f"╔══════════════════════════════════════════╗")
    print(f"║  PRICE RESYNC — {mode} — {target}")
    print(f"║  {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S UTC')}")
    print(f"╚══════════════════════════════════════════╝")

    do_steam = args.steam or not args.xbox
    do_xbox = args.xbox or not args.steam

    if do_steam:
        resync_steam(conn, args.dry_run)

    if do_xbox:
        resync_xbox(conn, args.dry_run)

    if args.dry_run:
        print("\n⚠ DRY-RUN: no se escribió nada en la base de datos.")
        conn.rollback()
    else:
        print("\n✓ Resync completado.")

    conn.close()


if __name__ == "__main__":
    main()