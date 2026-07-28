"""
Steam Argentina Store Scraper (HTTP-only)
==========================================
Pipeline en 2 fases:
  1. Descubrimiento: HTML search results (1-3 requests) → app_ids + precios + reviews
  2. Enriquecimiento: appdetails × N (con delay 1s) → géneros + metacritic + imágenes

Los precios se obtienen en USD (cents en el HTML, convertidos a dólares).
La conversión a ARS la hace el server vía dolarapi.com.

Incrementalidad: solo re-scrapea juegos cuyo último precio tenga > 24h.
Usa la tabla scrape_log (store_id=2 para steam_argentina).

Uso:
  python scrapers/steam_scraper.py           # Incremental (>24h)
  python scrapers/steam_scraper.py --force   # Re-scrapea todo
  python scrapers/steam_scraper.py --help    # Ayuda
"""
import argparse
import logging
import re
import sqlite3
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import requests
from bs4 import BeautifulSoup

DB_PATH = str(Path(__file__).parent.parent / "data" / "games.db")
STORE_ID = 2  # steam_argentina

SEARCH_URL = "https://store.steampowered.com/search/results/"
APPDETAILS_URL = "https://store.steampowered.com/api/appdetails"

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/131.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "es-AR,es;q=0.9,en;q=0.8",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
}

MAX_RETRIES = 3
RETRY_BACKOFF = [1, 2, 4]  # seconds between retries
REQUEST_DELAY = 1.0  # seconds between appdetails requests
STALE_HOURS = 24      # re-scrape if last price is older than this


# ---------------------------------------------------------------------------
#  Helpers
# ---------------------------------------------------------------------------

def parse_args():
    parser = argparse.ArgumentParser(
        description="Steam AR Scraper — descubre y enriquece juegos del catálogo Steam Argentina",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Ignora incrementalidad y re-scrapea todos los juegos",
    )
    return parser.parse_args()


def http_get(url, params=None, max_retries=MAX_RETRIES):
    """HTTP GET con retry y backoff exponencial. Respeta Retry-After en 429."""
    last_error = None
    for attempt in range(max_retries):
        try:
            resp = requests.get(url, params=params, headers=HEADERS, timeout=30)
            if resp.status_code == 429:
                retry_after = resp.headers.get("Retry-After")
                if retry_after and retry_after.isdigit():
                    wait = int(retry_after)
                else:
                    wait = RETRY_BACKOFF[min(attempt, len(RETRY_BACKOFF) - 1)]
                logging.warning("Rate limited (429), waiting %ds...", wait)
                time.sleep(wait)
                continue
            resp.raise_for_status()
            return resp
        except requests.RequestException as exc:
            last_error = exc
            if attempt < max_retries - 1:
                wait = RETRY_BACKOFF[min(attempt, len(RETRY_BACKOFF) - 1)]
                logging.warning(
                    "Request failed (%s), retrying in %ds (attempt %d/%d)",
                    exc, wait, attempt + 1, max_retries,
                )
                time.sleep(wait)
    raise last_error


def parse_html_price(raw_cents):
    """Convierte cents (int de data-price-final) a dólares (float)."""
    if raw_cents is None:
        return None
    try:
        return int(raw_cents) / 100.0
    except (ValueError, TypeError):
        return None


def parse_formatted_price(text):
    """Parsea un precio formateado como '$1,234.56 USD' o '$47.99' a float."""
    if not text:
        return None
    match = re.search(r"[\d,]+\.?\d*", text.replace("USD", "").replace("$", ""))
    if match:
        try:
            return float(match.group().replace(",", ""))
        except ValueError:
            return None
    return None


# ---------------------------------------------------------------------------
#  Phase 1 — HTML Search Parser
# ---------------------------------------------------------------------------

def parse_search_html(html):
    """Extrae datos de cada fila de resultado en el HTML de búsqueda de Steam.

    Retorna una lista de dicts con: app_id, name, price, original_price,
    discount_percent, is_free, release_date, review_summary, platforms,
    capsule_url, url.
    """
    soup = BeautifulSoup(html, "html.parser")
    results = []

    for row in soup.find_all("a", class_="search_result_row"):
        app_id = row.get("data-ds-appid")
        if not app_id:
            continue

        # ── title ──
        title_el = row.find("span", class_="title")
        if not title_el:
            continue
        name = title_el.text.strip()

        # ── price (cents → USD) ──
        # data-price-final lives on the <div class="search_price_discount_combined">
        # inside the <a> row, NOT directly on the <a> tag.
        price_combined = row.find(
            "div", class_="search_price_discount_combined"
        )
        price = parse_html_price(
            price_combined.get("data-price-final") if price_combined else None
        )
        if price is None:
            price = 0.0

        # ── discount & is_free detection ──
        discount_pct = 0
        original_price = None
        is_free = False

        final_price_div = row.find("div", class_="discount_final_price")
        if final_price_div:
            classes = final_price_div.get("class", [])
            if "free" in classes:
                is_free = True
                price = 0.0
                original_price = 0.0
            else:
                # Parse formatted price from text content (backup for price)
                parsed_p = parse_formatted_price(final_price_div.text)
                if parsed_p and price == 0.0:
                    price = parsed_p

        # ── fallback for non-discounted games (search_price div) ──
        if price == 0.0 and not is_free:
            price_div = row.find("div", class_="search_price")
            if price_div:
                price_text = price_div.text.strip()
                # Skip if it just says "Free" or "Gratuito"
                if price_text.lower() not in ("free", "gratuito", "free to play", ""):
                    parsed_p = parse_formatted_price(price_text)
                    if parsed_p:
                        price = parsed_p

        # discount percentage
        pct_el = row.find("div", class_="discount_pct")
        if pct_el:
            pct_text = pct_el.text.strip().replace("-", "").replace("%", "").strip()
            try:
                discount_pct = int(pct_text)
            except ValueError:
                discount_pct = 0

        # original price (formatted text, only present when discounted)
        orig_el = row.find("div", class_="discount_original_price")
        if orig_el:
            original_price = parse_formatted_price(orig_el.text)

        if original_price is None:
            original_price = price

        # ── release date ──
        release_el = row.find("div", class_="search_released")
        release_date = release_el.text.strip() if release_el else None

        # ── review summary ──
        review_summary = None
        review_el = row.find("span", class_="search_review_summary")
        if review_el:
            tooltip = review_el.get("data-tooltip-html")
            if tooltip:
                review_summary = tooltip.strip()
            else:
                review_summary = review_el.text.strip()

        # ── platforms ──
        platforms = []
        if row.find("span", class_="platform_img win"):
            platforms.append("windows")
        if row.find("span", class_="platform_img mac"):
            platforms.append("mac")
        if row.find("span", class_="platform_img linux"):
            platforms.append("linux")
        platforms_str = ", ".join(platforms) if platforms else None

        # ── capsule image ──
        capsule_url = None
        capsule_div = row.find("div", class_="search_capsule")
        if capsule_div:
            img_tag = capsule_div.find("img")
            if img_tag:
                capsule_url = img_tag.get("src")

        # ── url ──
        url = row.get("href", "")

        results.append({
            "app_id": app_id,
            "name": name,
            "price": price,
            "original_price": original_price,
            "discount_percent": discount_pct,
            "is_free": is_free,
            "release_date": release_date,
            "review_summary": review_summary,
            "platforms": platforms_str,
            "capsule_url": capsule_url,
            "url": url,
        })

    return results


# ---------------------------------------------------------------------------
#  Phase 2 — App Details Enrichment
# ---------------------------------------------------------------------------

def enrich_with_appdetails(app_id):
    """Consulta /api/appdetails para un app_id y extrae metadata adicional.

    Retorna un dict con: genres, metacritic_score, header_image,
    short_description, developers, publishers, price_overview, is_free.
    Retorna None si la API falla o success=false.
    """
    try:
        resp = http_get(APPDETAILS_URL, params={"appids": app_id, "cc": "ar"})
        data = resp.json()
        app_data = data.get(str(app_id), {})
        if not app_data.get("success"):
            logging.debug("appdetails success=false for %s", app_id)
            return None

        info = app_data["data"]

        # genres
        genres = [g["description"] for g in info.get("genres", [])]

        # metacritic
        metacritic_score = None
        mc = info.get("metacritic")
        if mc and mc.get("score"):
            metacritic_score = mc["score"]

        # price_overview (fallback)
        price_overview = None
        po = info.get("price_overview")
        if po:
            price_overview = {
                "final": po.get("final", 0) / 100.0,
                "initial": po.get("initial", 0) / 100.0,
                "discount_percent": po.get("discount_percent", 0),
            }

        return {
            "genres": genres,
            "metacritic_score": metacritic_score,
            "header_image": info.get("header_image"),
            "short_description": info.get("short_description"),
            "developers": info.get("developers", []),
            "publishers": info.get("publishers", []),
            "price_overview": price_overview,
            "is_free": info.get("is_free", False),
        }

    except Exception as exc:
        logging.error("Error en appdetails para %s: %s", app_id, exc)
        return None


# ---------------------------------------------------------------------------
#  Main Pipeline
# ---------------------------------------------------------------------------

def main():
    logger = logging.getLogger("steam_scraper")
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
        stream=sys.stdout,
    )
    args = parse_args()

    logger.info("=" * 60)
    logger.info("Steam Argentina Scraper — Iniciando")
    logger.info(
        "Modo: %s",
        "FORCE (re-scrapeo total)" if args.force else f"INCREMENTAL (>{STALE_HOURS}h)",
    )
    logger.info("=" * 60)

    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()
    now_utc = datetime.now(timezone.utc).isoformat()

    # ── scrape_log: start ──
    cur.execute(
        "INSERT INTO scrape_log (store_id, started_at, status) VALUES (?, ?, 'running')",
        (STORE_ID, now_utc),
    )
    log_id = cur.lastrowid
    conn.commit()

    games_found = 0
    games_new = 0
    games_updated = 0
    games_skipped = 0
    errors = 0

    try:
        # ==================================================================
        #  PHASE 1 — Discovery via HTML search
        # ==================================================================
        logger.info("Fase 1: Descubriendo juegos desde search/results HTML...")

        all_games = []
        for start in (0, 100, 200):
            params = {
                "query": "",
                "start": start,
                "count": 100,
                "cc": "ar",
                "l": "spanish",
                "category1": "998",
            }
            resp = http_get(SEARCH_URL, params=params)
            batch = parse_search_html(resp.text)
            all_games.extend(batch)
            logger.info("  Página start=%d: %d juegos", start, len(batch))

            if len(batch) < 100:
                break  # no hay más resultados

        # deduplicate by app_id
        seen = set()
        unique_games = []
        for g in all_games:
            if g["app_id"] not in seen:
                seen.add(g["app_id"])
                unique_games.append(g)

        games_found = len(unique_games)
        logger.info("Total descubiertos (únicos): %d", games_found)

        # ==================================================================
        #  Determine which games to scrape (incremental filter)
        # ==================================================================
        to_scrape = []
        for game in unique_games:
            app_id = game["app_id"]

            cur.execute(
                """SELECT g.id, g.last_seen,
                          (SELECT p.scraped_at FROM prices p
                           WHERE p.game_id = g.id
                           ORDER BY p.scraped_at DESC LIMIT 1) AS last_price_at
                   FROM games g
                   WHERE g.store_id = ? AND g.store_game_id = ?""",
                (STORE_ID, app_id),
            )
            row = cur.fetchone()

            if row:
                game["existing_id"] = row["id"]
                last_price_at = row["last_price_at"]

                if not args.force and last_price_at:
                    try:
                        last_dt = datetime.fromisoformat(
                            last_price_at.replace("Z", "+00:00")
                        )
                        age_hours = (
                            datetime.now(timezone.utc) - last_dt
                        ).total_seconds() / 3600
                        if age_hours < STALE_HOURS:
                            games_skipped += 1
                            continue
                    except (ValueError, TypeError):
                        pass  # malformed date → re-scrape

            to_scrape.append(game)

        logger.info(
            "Juegos a procesar: %d (omitidos por incrementalidad: %d)",
            len(to_scrape), games_skipped,
        )

        # ==================================================================
        #  PHASE 2 — Enrich via appdetails & save to DB
        # ==================================================================
        logger.info("Fase 2: Enriqueciendo vía appdetails y guardando...")

        for i, game in enumerate(to_scrape):
            app_id = game["app_id"]
            name = game["name"]

            # progress report every 10 games + first
            if (i + 1) % 10 == 0 or i == 0:
                logger.info(
                    "  Progreso: %d/%d — %s",
                    i + 1, len(to_scrape), name,
                )

            # ── fetch appdetails (with error handling) ──
            enrichment = None
            try:
                enrichment = enrich_with_appdetails(app_id)
            except Exception as exc:
                logger.error("  ERROR appdetails %s (%s): %s", app_id, name, exc)
                errors += 1

            # ── resolve final price ──
            price = game["price"]
            original_price = game["original_price"]
            discount_pct = game["discount_percent"]
            is_free = game["is_free"]

            if enrichment:
                if enrichment.get("is_free"):
                    is_free = True
                    price = 0.0
                    original_price = 0.0

                # fallback to price_overview if search had no price
                po = enrichment.get("price_overview")
                if po and price == 0.0 and not is_free:
                    price = po["final"]
                    original_price = po["initial"]
                    discount_pct = po["discount_percent"]

            # ── upsert game ──
            cover = None
            if enrichment and enrichment.get("header_image"):
                cover = enrichment["header_image"]
            else:
                cover = game.get("capsule_url")

            if "existing_id" in game:
                game_id = game["existing_id"]
                cur.execute(
                    """UPDATE games
                       SET title = ?, url = ?, cover_url = ?, platforms = ?,
                           last_seen = ?
                       WHERE id = ?""",
                    (name, game["url"], cover, game.get("platforms"),
                     now_utc, game_id),
                )
                games_updated += 1
            else:
                cur.execute(
                    """INSERT INTO games
                         (store_id, store_game_id, title, url, cover_url,
                          platforms, first_seen, last_seen)
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                    (STORE_ID, app_id, name, game["url"], cover,
                     game.get("platforms"), now_utc, now_utc),
                )
                game_id = cur.lastrowid
                games_new += 1

            # ── upsert price row (INSERT or UPDATE if game already has a price) ──
            cur.execute(
                """INSERT INTO prices
                     (game_id, price, original_price, discount_percent,
                      is_free, scraped_at)
                   VALUES (?, ?, ?, ?, ?, ?)
                   ON CONFLICT(game_id) DO UPDATE SET
                     price=excluded.price,
                     original_price=excluded.original_price,
                     discount_percent=excluded.discount_percent,
                     is_free=excluded.is_free,
                     scraped_at=excluded.scraped_at""",
                (game_id, price, original_price, discount_pct,
                 int(is_free), now_utc),
            )

            conn.commit()

            # ── rate-limit ──
            time.sleep(REQUEST_DELAY)

        # ==================================================================
        #  scrape_log: complete
        # ==================================================================
        cur.execute(
            """UPDATE scrape_log
               SET finished_at = ?, games_found = ?, games_new = ?,
                   status = 'completed'
               WHERE id = ?""",
            (datetime.now(timezone.utc).isoformat(), games_found, games_new,
             log_id),
        )
        conn.commit()

        logger.info("=" * 60)
        logger.info("SCRAPE COMPLETADO")
        logger.info("  Juegos encontrados:  %d", games_found)
        logger.info("  Juegos nuevos:       %d", games_new)
        logger.info("  Juegos actualizados:  %d", games_updated)
        logger.info("  Juegos omitidos:     %d (precio < %dh)", games_skipped, STALE_HOURS)
        logger.info("  Errores:             %d", errors)
        logger.info("=" * 60)

    except Exception as exc:
        logger.error("FATAL: %s", exc, exc_info=True)
        try:
            cur.execute(
                """UPDATE scrape_log
                   SET finished_at = ?, status = 'failed', error_message = ?
                   WHERE id = ?""",
                (datetime.now(timezone.utc).isoformat(), str(exc), log_id),
            )
            conn.commit()
        except Exception:
            pass
        sys.exit(1)

    finally:
        conn.close()


if __name__ == "__main__":
    main()