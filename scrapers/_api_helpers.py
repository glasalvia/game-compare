#!/usr/bin/env python3
"""Helpers compartidos: APIs Steam/IGDB/Xbox + DB."""

import os
import re
import time
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

import requests
from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parent.parent / ".env")

# ── Config ──
TWITCH_CLIENT_ID = os.getenv("TWITCH_CLIENT_ID")
TWITCH_CLIENT_SECRET = os.getenv("TWITCH_CLIENT_SECRET")
DB_PATH = str(Path(__file__).resolve().parent.parent / "data" / "games.db")

STEAM_API = "https://store.steampowered.com/api/appdetails"
IGDB_API = "https://api.igdb.com/v4"
TWITCH_AUTH = "https://id.twitch.tv/oauth2/token"
XBOX_API = "https://displaycatalog.mp.microsoft.com/v7.0/products"

STEAM_DELAY = 1.0
IGDB_DELAY = 0.28
XBOX_DELAY = 0.15
MAX_RETRIES = 3


def steam_price(app_id):
    """Obtiene precio de Steam API (appdetails). Retorna dict o None."""
    time.sleep(STEAM_DELAY)
    url = f"{STEAM_API}?appids={app_id}&cc=ar"
    
    for attempt in range(MAX_RETRIES):
        try:
            resp = requests.get(url, timeout=15)
            if resp.status_code != 200:
                if attempt < MAX_RETRIES - 1:
                    time.sleep(2 ** attempt)
                continue
            
            data = resp.json()
            game_data = data.get(str(app_id), {})
            
            if not game_data.get("success"):
                return None
            
            info = game_data.get("data", {})
            
            # ¿Gratuito?
            if info.get("is_free", False):
                return {
                    "price_usd": 0.0,
                    "original_usd": 0.0,
                    "discount_pct": 0,
                    "is_free": True,
                    "currency": "USD",
                }
            
            # Precio con descuento
            price_overview = info.get("price_overview", {})
            if price_overview:
                price_final = price_overview.get("final", 0)
                price_initial = price_overview.get("initial", price_final)
                discount = price_overview.get("discount_percent", 0)
                return {
                    "price_usd": price_final / 100.0,
                    "original_usd": price_initial / 100.0,
                    "discount_pct": discount,
                    "is_free": False,
                    "currency": price_overview.get("currency", "USD"),
                }
            
            # Sin price_overview: podría ser contenido adicional, no aplicación
            return None
            
        except (requests.RequestException, KeyError, ValueError) as e:
            if attempt < MAX_RETRIES - 1:
                time.sleep(2 ** attempt)
            continue
    
    return None


def igdb_token():
    """Obtiene token OAuth2 de Twitch para IGDB."""
    resp = requests.post(TWITCH_AUTH, params={
        "client_id": TWITCH_CLIENT_ID,
        "client_secret": TWITCH_CLIENT_SECRET,
        "grant_type": "client_credentials",
    }, timeout=15)
    return resp.json()["access_token"] if resp.status_code == 200 else None


def igdb_call(token, endpoint, body):
    """POST a IGDB v4."""
    time.sleep(IGDB_DELAY)
    headers = {
        "Client-ID": TWITCH_CLIENT_ID,
        "Authorization": f"Bearer {token}",
        "Accept": "application/json",
    }
    for attempt in range(MAX_RETRIES):
        try:
            resp = requests.post(f"{IGDB_API}/{endpoint}", data=body,
                                headers=headers, timeout=15)
            if resp.status_code == 401:
                token = igdb_token()
                if token:
                    headers["Authorization"] = f"Bearer {token}"
                    time.sleep(IGDB_DELAY)
                    resp = requests.post(f"{IGDB_API}/{endpoint}", data=body,
                                        headers=headers, timeout=15)
            if resp.status_code == 429:
                time.sleep(2 ** attempt)
                continue
            return resp.json() if resp.status_code == 200 else []
        except requests.RequestException:
            if attempt < MAX_RETRIES - 1:
                time.sleep(2 ** attempt)
    return []


def xbox_price(product_id):
    """Obtiene precio ARS de Microsoft Display Catalog API."""
    time.sleep(XBOX_DELAY)
    url = (f"{XBOX_API}?bigIds={product_id}&market=AR"
           f"&languages=es-ar&actionFilter=Purchase")
    
    for attempt in range(MAX_RETRIES):
        try:
            resp = requests.get(url, headers={
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)",
                "MS-CV": f"defpipe.{attempt}",
            }, timeout=15)
            
            if resp.status_code != 200:
                continue
            
            data = resp.json()
            products = data.get("Products", [])
            if not products:
                return None
            
            product = products[0]
            
            # Título
            title = None
            for lp in product.get("LocalizedProperties", []):
                title = lp.get("ProductTitle")
                if title:
                    break
            
            # Plataformas jugables (AllowedPlatforms)
            playable_platforms = set()
            for sku_avail in product.get("DisplaySkuAvailabilities", []):
                for avail in sku_avail.get("Availabilities", []):
                    for ap in avail.get("Conditions", {}).get("ClientConditions", {}).get("AllowedPlatforms", []):
                        pn = ap.get("PlatformName", "")
                        if pn == "Windows.Xbox":
                            playable_platforms.add("Xbox")
                        elif pn == "Windows.Desktop":
                            playable_platforms.add("PC")
                        elif pn:
                            playable_platforms.add(pn)
            playable_on = "+".join(sorted(playable_platforms)) if playable_platforms else None

            # Precio
            for sku_avail in product.get("DisplaySkuAvailabilities", []):
                for avail in sku_avail.get("Availabilities", []):
                    price_data = avail.get("OrderManagementData", {}).get("Price", {})
                    list_price = price_data.get("ListPrice")
                    
                    if list_price is not None and list_price > 0:
                        return {
                            "title": title,
                            "price_ars": list_price,
                            "msrp_ars": price_data.get("MSRP"),
                            "wholesale_ars": price_data.get("WholesalePrice"),
                            "currency": price_data.get("CurrencyCode", "ARS"),
                            "is_free": False,
                            "is_game_pass": False,
                            "playable_on": playable_on,
                        }
            
            # Sin precio > 0 → Game Pass o gratis
            return {
                "title": title,
                "price_ars": 0.0,
                "is_free": True,
                "is_game_pass": True,
                "currency": "ARS",
                "playable_on": playable_on,
            }
            
        except (requests.RequestException, KeyError, ValueError):
            if attempt < MAX_RETRIES - 1:
                time.sleep(2 ** attempt)
    
    return None


def ensure_game(conn, store_id, store_game_id, title):
    """Garantiza que el juego existe en la tabla games. Retorna game_id."""
    existing = conn.execute(
        "SELECT id FROM games WHERE store_id = ? AND store_game_id = ?",
        (store_id, store_game_id)
    ).fetchone()
    
    if existing:
        return existing[0]
    
    # Construir URL según store
    if store_id == 2:  # Steam
        url = f"https://store.steampowered.com/app/{store_game_id}/"
    else:  # Xbox
        url = f"https://www.xbox.com/es-ar/games/store/-/{store_game_id}"
    
    cursor = conn.execute(
        "INSERT INTO games (store_id, store_game_id, title, url) VALUES (?, ?, ?, ?)",
        (store_id, store_game_id, title, url)
    )
    return cursor.lastrowid


def upsert_price(conn, game_id, price, original_price, discount_pct, 
                 is_free, currency, source):
    """Inserta o actualiza precio del juego."""
    existing = conn.execute(
        "SELECT id, price FROM prices WHERE game_id = ? ORDER BY scraped_at DESC LIMIT 1",
        (game_id,)
    ).fetchone()
    
    if existing and existing["price"] == price:
        # Precio no cambió, actualizar verificación nomás
        conn.execute("""
            UPDATE prices SET price_verified = 1, verified_at = CURRENT_TIMESTAMP,
                   verified_source = ? WHERE id = ?
        """, (source, existing["id"]))
        return
    
    conn.execute("""
        INSERT INTO prices (game_id, price, original_price, discount_percent,
                           is_free, price_verified, verified_at, verified_source)
        VALUES (?, ?, ?, ?, ?, 1, CURRENT_TIMESTAMP, ?)
    """, (game_id, price, original_price, discount_pct, is_free, source))


def store_match(conn, steam_app_id, steam_title, steam_price_data,
                igdb_game_id, xbox_id, xbox_data):
    """Almacena un match completo en la DB."""
    
    # 1. Steam game
    steam_db_id = ensure_game(conn, 2, steam_app_id, steam_title)
    
    # 2. Xbox game
    xbox_title = xbox_data.get("title") or steam_title
    xbox_db_id = ensure_game(conn, 1, xbox_id, xbox_title)
    
    # 3. Precio Steam
    upsert_price(
        conn, steam_db_id,
        steam_price_data["price_usd"],
        steam_price_data["original_usd"],
        steam_price_data["discount_pct"],
        1 if steam_price_data["is_free"] else 0,
        steam_price_data.get("currency", "USD"),
        "steam_api_definitive"
    )
    
    # 4. Precio Xbox
    upsert_price(
        conn, xbox_db_id,
        xbox_data["price_ars"],
        xbox_data.get("msrp_ars"),
        0,  # Xbox API no reporta discount_percent
        1 if xbox_data.get("is_free") else 0,
        xbox_data.get("currency", "ARS"),
        "display_catalog_definitive"
    )
    
    # 5. Match table
    conn.execute("""
        INSERT OR REPLACE INTO igdb_steam_to_xbox
            (steam_game_id, steam_app_id, igdb_game_id, xbox_store_id,
             steam_price_usd, steam_original_usd, steam_discount_pct,
             steam_is_free,
             xbox_title, xbox_price_ars, xbox_msrp_ars, xbox_wholesale_ars,
             xbox_currency, xbox_is_free, xbox_is_game_pass,
             matched_at, source, xbox_playable_on, platforms)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP, 'definitive_pipeline_v3', ?, ?)
    """, (
        steam_db_id, steam_app_id, igdb_game_id, xbox_id,
        steam_price_data["price_usd"],
        steam_price_data["original_usd"],
        steam_price_data["discount_pct"],
        1 if steam_price_data["is_free"] else 0,
        xbox_data.get("title"),
        xbox_data["price_ars"],
        xbox_data.get("msrp_ars"),
        xbox_data.get("wholesale_ars"),
        xbox_data.get("currency", "ARS"),
        1 if xbox_data.get("is_free") else 0,
        1 if xbox_data.get("is_game_pass") else 0,
        xbox_data.get("playable_on"),
        None,  # platforms se backfillean desde IGDB
    ))
    
    return True


def save_checkpoint(conn, steam_app_id, count):
    """Guarda checkpoint para resume."""
    conn.execute("""
        UPDATE pipeline_checkpoint 
        SET last_steam_app_id = ?, processed_count = ?, updated_at = CURRENT_TIMESTAMP
        WHERE id = 1
    """, (steam_app_id, count))