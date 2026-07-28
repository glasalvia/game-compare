#!/usr/bin/env python3
"""Benchmark metrics for igdb_steam_to_xbox matches."""

import sqlite3
import statistics
from pathlib import Path

DB_PATH = Path(__file__).resolve().parent.parent / "data" / "games.db"


def main():
    conn = sqlite3.connect(str(DB_PATH))
    cur = conn.cursor()

    # Juegos por tienda
    cur.execute(
        "SELECT s.name, COUNT(g.id) FROM games g "
        "JOIN stores s ON g.store_id = s.id GROUP BY s.name"
    )
    store_counts = dict(cur.fetchall())  # {"steam_argentina": 341, "xbox_argentina": 277}

    steam_count = store_counts.get("steam_argentina", 0)
    xbox_count = store_counts.get("xbox_argentina", 0)

    # Matches
    cur.execute("SELECT COUNT(*) FROM igdb_steam_to_xbox")
    total_matches = cur.fetchone()[0]

    cur.execute(
        "SELECT COUNT(*) FROM igdb_steam_to_xbox "
        "WHERE steam_price_usd > 0 AND xbox_price_ars > 0"
    )
    comparable = cur.fetchone()[0]

    cur.execute(
        "SELECT COUNT(*) FROM igdb_steam_to_xbox WHERE xbox_is_game_pass = 1"
    )
    game_pass = cur.fetchone()[0]

    # Multiplicadores (solo cuando ambos > 0)
    cur.execute(
        "SELECT xbox_price_ars, steam_price_usd FROM igdb_steam_to_xbox "
        "WHERE steam_price_usd > 0 AND xbox_price_ars > 0"
    )
    rows = cur.fetchall()
    multipliers = [row[0] / row[1] for row in rows]

    avg_mult = statistics.mean(multipliers)
    median_mult = statistics.median(multipliers)
    min_mult = min(multipliers)
    max_mult = max(multipliers)

    # Top 5 — Xbox más caro (mayor diferencia absoluta en ARS)
    cur.execute(
        "SELECT xbox_title, xbox_price_ars, steam_price_usd FROM igdb_steam_to_xbox "
        "WHERE steam_price_usd > 0 AND xbox_price_ars > 0 "
        "ORDER BY xbox_price_ars DESC LIMIT 5"
    )
    top_expensive = cur.fetchall()

    # Top 5 — Mejor relación (menor multiplicador)
    cur.execute(
        "SELECT xbox_title, xbox_price_ars, steam_price_usd FROM igdb_steam_to_xbox "
        "WHERE steam_price_usd > 0 AND xbox_price_ars > 0 "
        "ORDER BY (xbox_price_ars * 1.0 / steam_price_usd) ASC LIMIT 5"
    )
    top_ratio = cur.fetchall()

    conn.close()

    # --- Output ---
    print("=== GAME COMPARE — MÉTRICAS ===\n")
    print("Juegos por tienda:")
    print(f"  Steam: {steam_count}")
    print(f"  Xbox:  {xbox_count}")
    print()
    print("Matches (igdb_steam_to_xbox):")
    print(f"  Total: {total_matches}")
    print(f"  Con precio comparable: {comparable}")
    print(f"  Xbox Game Pass: {game_pass}")
    print()
    print("Multiplicador ARS/USD (solo cuando ambos precios > 0):")
    print(f"  Promedio: {avg_mult:.2f}")
    print(f"  Mediana:  {median_mult:.2f}")
    print(f"  Mínimo:   {min_mult:.2f}")
    print(f"  Máximo:   {max_mult:.2f}")
    print()
    print("Top 5 — Xbox más caro:")
    for i, (title, price_ars, _price_usd) in enumerate(top_expensive, 1):
        display_title = title if title else "(sin título)"
        if len(display_title) > 30:
            display_title = display_title[:27] + "..."
        print(f"  {i}. {display_title:<30} ARS ${price_ars:,.2f}")

    print()
    print("Top 5 — Mejor relación (menor multiplicador):")
    for i, (title, price_ars, price_usd) in enumerate(top_ratio, 1):
        ratio = price_ars / price_usd
        display_title = title if title else "(sin título)"
        if len(display_title) > 30:
            display_title = display_title[:27] + "..."
        print(f"  {i}. {display_title:<30} ×{ratio:.2f}")


if __name__ == "__main__":
    main()
