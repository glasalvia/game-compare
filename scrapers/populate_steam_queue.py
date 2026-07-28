#!/usr/bin/env python3
"""
Popula steam_queue con 200 app_ids de cada categoría de Steam:
  1. Novedades populares (popularnew) — 200
  2. Lo más vendido (topsellers) — 200
  3. Ofertas (specials=1) — 200

Total: hasta 600 IDs únicos para procesar con definitive_pipeline.py.

Uso:
  python populate_steam_queue.py
"""

import sqlite3
import sys
import time
from pathlib import Path

import requests
from bs4 import BeautifulSoup

DB_PATH = str(Path(__file__).resolve().parent.parent / "data" / "games.db")
SEARCH_URL = "https://store.steampowered.com/search/results/"

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/131.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "es-AR,es;q=0.9,en;q=0.8",
}

MAX_RETRIES = 3
RETRY_BACKOFF = [1, 2, 4]


def http_get(url, params):
    """HTTP GET con retry."""
    last_error = None
    for attempt in range(MAX_RETRIES):
        try:
            resp = requests.get(url, params=params, headers=HEADERS, timeout=30)
            if resp.status_code == 429:
                wait = RETRY_BACKOFF[min(attempt, len(RETRY_BACKOFF) - 1)]
                print(f"  Rate limited (429), esperando {wait}s...")
                time.sleep(wait)
                continue
            resp.raise_for_status()
            return resp
        except requests.RequestException as exc:
            last_error = exc
            if attempt < MAX_RETRIES - 1:
                wait = RETRY_BACKOFF[min(attempt, len(RETRY_BACKOFF) - 1)]
                time.sleep(wait)
    raise last_error


def extract_app_ids(html):
    """Extrae app_ids del HTML de resultados de Steam."""
    soup = BeautifulSoup(html, "html.parser")
    ids = []
    for row in soup.find_all("a", class_="search_result_row"):
        app_id = row.get("data-ds-appid")
        if app_id:
            ids.append(app_id)
    return ids


def scrape_category(name, params_template, count=200):
    """Scrapea count IDs de una categoría (2 páginas de 100)."""
    all_ids = []
    pages_needed = (count + 99) // 100  # 2 páginas para 200

    for page in range(pages_needed):
        params = {**params_template, "start": page * 100, "count": 100}
        try:
            resp = http_get(SEARCH_URL, params)
            page_ids = extract_app_ids(resp.text)
            all_ids.extend(page_ids)
            print(f"  {name} página {page+1}: {len(page_ids)} IDs")
        except Exception as e:
            print(f"  ERROR {name} página {page+1}: {e}")
            break

        if page < pages_needed - 1:
            time.sleep(1.5)

    return all_ids


def main():
    print("=" * 60)
    print("  POBLANDO steam_queue — 3 categorías × 200 IDs")
    print("=" * 60)

    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row

    # Asegurar tabla
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS steam_queue (
            steam_app_id TEXT PRIMARY KEY,
            added_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            processed_at TIMESTAMP,
            status TEXT DEFAULT 'pending'
        );
    """)

    # ── Categorías ──────────────────────────────────────────────
    categories = [
        ("Novedades populares", {"query": "", "cc": "ar", "l": "spanish", "filter": "popularnew", "category1": "998"}),
        ("Lo más vendido",      {"query": "", "cc": "ar", "l": "spanish", "filter": "topsellers", "category1": "998"}),
        ("Ofertas",             {"query": "", "cc": "ar", "l": "spanish", "specials": "1", "category1": "998"}),
    ]

    total_inserted = 0
    total_skipped = 0

    for name, params_template in categories:
        print(f"\n── {name} ──")
        ids = scrape_category(name, params_template, count=200)
        unique_ids = list(dict.fromkeys(ids))  # preserve order, dedup

        inserted = 0
        skipped = 0
        for app_id in unique_ids[:200]:
            try:
                conn.execute(
                    "INSERT OR IGNORE INTO steam_queue (steam_app_id) VALUES (?)",
                    (app_id,)
                )
                if conn.total_changes > 0:
                    inserted += 1
                else:
                    skipped += 1
            except Exception as e:
                print(f"  ERROR DB {app_id}: {e}")

        conn.commit()
        total_inserted += inserted
        total_skipped += skipped
        print(f"  → {inserted} nuevos, {skipped} ya existentes (total extraídos: {len(unique_ids)})")

        time.sleep(1.5)

    # ── Resumen ──
    pending = conn.execute("SELECT COUNT(*) FROM steam_queue WHERE status='pending'").fetchone()[0]
    total = conn.execute("SELECT COUNT(*) FROM steam_queue").fetchone()[0]

    print(f"\n{'=' * 60}")
    print(f"  RESULTADO")
    print(f"  Nuevos insertados:  {total_inserted}")
    print(f"  Ya existentes:      {total_skipped}")
    print(f"  Pendientes totales: {pending}")
    print(f"  Total en cola:      {total}")
    print(f"{'=' * 60}")

    conn.close()


if __name__ == "__main__":
    main()