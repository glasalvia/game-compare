#!/usr/bin/env python3
"""
Pipeline Xbox → Steam v1.0 — Descubrimiento inverso desde catálogo Xbox en IGDB.

Flujo INVERTIDO:
  1. IGDB → juegos de plataformas Xbox (One + Series X|S)
  2. Extraer pares Steam ↔ Xbox desde external_games
  3. Steam API → precio USD
  4. Xbox Display Catalog API → precio ARS
  5. INSERT en igdb_steam_to_xbox + games + prices (solo si ambos precios OK)

A diferencia de steam_xbox_pipeline (que parte de Steam), este pipeline:
  - Parte del catálogo completo de Xbox en IGDB
  - Descubre juegos que existen en ambas plataformas
  - Usa producto cartesiano: N Steam IDs × M Xbox IDs por juego
  - Checkpoint por IGDB offset (no por steam_app_id)

Principios:
  - Cero scraping HTML. Ambas fuentes de precio son APIs JSON.
  - Solo se almacenan juegos con match confirmado y precios válidos.
  - Idempotente: skips por producto cartesiano vía INSERT OR REPLACE.
  - Commit cada N procesados. Resumible (Ctrl+C guarda progreso).
  - Source: 'xbox_steam_pipeline_v1'

Uso:
  python xbox_steam_pipeline.py                    # Desde offset 0, sin límite
  python xbox_steam_pipeline.py --limit 200        # Procesa 200 juegos IGDB
  python xbox_steam_pipeline.py --offset 1000 --limit 500  # Desde offset 1000
  python xbox_steam_pipeline.py --resume           # Continúa desde checkpoint
  python xbox_steam_pipeline.py --verbose          # Muestra cada juego
"""

import argparse
import re
import signal
import sqlite3
import sys
import time

from scrapers._api_helpers import (
    DB_PATH,
    IGDB_API,
    TWITCH_AUTH,
    IGDB_DELAY,
    igdb_token,
    igdb_call,
    steam_price,
    xbox_price,
    ensure_game,
    upsert_price,
    store_match,
)

# ── Config ──────────────────────────────────────────────────────────

COMMIT_EVERY = 25          # Guardar DB cada N partidos
PAGE_SIZE = 500            # Tamaño de página IGDB
PIPELINE_SOURCE = "xbox_steam_pipeline_v1"
CHECKPOINT_ID = 2          # id=1 es steam_xbox_pipeline

# Plataformas Xbox en IGDB
XBOX_PLATFORM_IDS = [49, 169]  # 49=Xbox One, 169=Xbox Series X|S

# Control de interrupción
SHUTDOWN = False


def _handle_signal(sig, frame):
    global SHUTDOWN
    print("\n⏸️  Interrupción detectada. Guardando progreso...")
    SHUTDOWN = True


signal.signal(signal.SIGINT, _handle_signal)
signal.signal(signal.SIGTERM, _handle_signal)


# ── DB Setup ────────────────────────────────────────────────────────


def ensure_tables(conn):
    """Crea tablas necesarias si no existen."""
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS igdb_steam_to_xbox (
            steam_game_id INTEGER NOT NULL,
            steam_app_id TEXT NOT NULL,
            igdb_game_id INTEGER,
            xbox_store_id TEXT,
            steam_price_usd REAL,
            steam_original_usd REAL,
            steam_discount_pct INTEGER DEFAULT 0,
            steam_is_free INTEGER DEFAULT 0,
            xbox_title TEXT,
            xbox_price_ars REAL,
            xbox_msrp_ars REAL,
            xbox_wholesale_ars REAL,
            xbox_currency TEXT DEFAULT 'ARS',
            xbox_is_free INTEGER DEFAULT 0,
            xbox_is_game_pass INTEGER DEFAULT 0,
            matched_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            source TEXT DEFAULT 'definitive_pipeline_v3',
            PRIMARY KEY (steam_game_id, xbox_store_id)
        );
    """)

    # Migrar pipeline_checkpoint si tiene CHECK (id=1) restrictivo del
    # steam_xbox_pipeline. Lo recreamos sin constraint para soportar id=2.
    cur = conn.execute(
        "SELECT sql FROM sqlite_master WHERE type='table' AND name='pipeline_checkpoint'"
    )
    row = cur.fetchone()
    if row and "CHECK (id = 1)" in (row[0] or ""):
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS pipeline_checkpoint_new (
                id INTEGER PRIMARY KEY,
                last_steam_app_id TEXT,
                processed_count INTEGER DEFAULT 0,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );
            INSERT OR IGNORE INTO pipeline_checkpoint_new SELECT * FROM pipeline_checkpoint;
            DROP TABLE pipeline_checkpoint;
            ALTER TABLE pipeline_checkpoint_new RENAME TO pipeline_checkpoint;
        """)
    else:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS pipeline_checkpoint (
                id INTEGER PRIMARY KEY,
                last_steam_app_id TEXT,
                processed_count INTEGER DEFAULT 0,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)

    conn.execute(
        "INSERT OR IGNORE INTO pipeline_checkpoint (id, last_steam_app_id, processed_count)"
        " VALUES (?, ?, ?)",
        (CHECKPOINT_ID, "", 0),
    )


# ── store_match wrapper (corrige source) ───────────────────────────


def store_match_xbox(conn, steam_app_id, steam_title, steam_price_data,
                     igdb_game_id, xbox_id, xbox_data):
    """
    Wrapper de store_match que corrige el source a 'xbox_steam_pipeline_v1'.
    store_match() usa 'definitive_pipeline_v3' hardcodeado;
    este wrapper hace UPDATE posterior para sobreescribirlo.
    """
    result = store_match(conn, steam_app_id, steam_title, steam_price_data,
                         igdb_game_id, xbox_id, xbox_data)
    conn.execute(
        """UPDATE igdb_steam_to_xbox
           SET source = ?, xbox_playable_on = ?
           WHERE steam_app_id = ? AND xbox_store_id = ?""",
        (PIPELINE_SOURCE, xbox_data.get("playable_on"), steam_app_id, xbox_id),
    )
    return result


# ── Fase 1+2: Discovery + extracción ───────────────────────────────


def igdb_fetch_xbox_catalog(token, offset, limit=PAGE_SIZE):
    """
    Consulta IGDB por juegos de plataformas Xbox y extrae pares Steam ↔ Xbox.

    Retorna lista de dicts:
        {
            "igdb_game_id": int,
            "name": str,
            "steam_ids": [str, ...],
            "xbox_ids": [str, ...],
        }
    """
    body = (
        "fields external_games.uid,external_games.url,external_games.category,name;"
        f"where platforms = [{','.join(map(str, XBOX_PLATFORM_IDS))}] "
        "& external_games != null;"
        f"limit {limit}; offset {offset};"
    )

    results = igdb_call(token, "games", body)

    XBOX_ID_RE = re.compile(r"^[A-Z0-9]{12}$")

    catalog = []
    for game in results:
        igdb_game_id = game.get("id")
        name = game.get("name", f"IGDB:{igdb_game_id}")

        if not igdb_game_id:
            continue

        steam_ids = set()
        xbox_ids = set()

        for eg in game.get("external_games", []):
            uid = eg.get("uid")
            if not uid:
                continue

            # Steam: category==1 o URL contiene "steampowered"
            if eg.get("category") == 1 or (
                eg.get("url") and "steampowered" in eg.get("url", "")
            ):
                steam_ids.add(uid)
                continue

            # Xbox: regex ^[A-Z0-9]{12}$
            if XBOX_ID_RE.match(uid):
                xbox_ids.add(uid)

        if steam_ids and xbox_ids:
            catalog.append({
                "igdb_game_id": igdb_game_id,
                "name": name,
                "steam_ids": sorted(steam_ids),
                "xbox_ids": sorted(xbox_ids),
            })

    return catalog


# ── Checkpoint ──────────────────────────────────────────────────────


def save_igdb_checkpoint(conn, offset, count):
    """Guarda checkpoint del pipeline invertido (id=2)."""
    conn.execute(
        """UPDATE pipeline_checkpoint
           SET last_steam_app_id = ?, processed_count = ?, updated_at = CURRENT_TIMESTAMP
           WHERE id = ?""",
        (str(offset), count, CHECKPOINT_ID),
    )


# ── Main Pipeline ───────────────────────────────────────────────────


def main():
    parser = argparse.ArgumentParser(
        description="Pipeline Xbox → Steam v1.0 (descubrimiento inverso)"
    )
    parser.add_argument("--offset", type=int, default=None,
                        help="Offset inicial en IGDB (default: 0 o checkpoint)")
    parser.add_argument("--limit", type=int, default=0,
                        help="Máximo de juegos IGDB a procesar (0 = sin límite)")
    parser.add_argument("--resume", action="store_true",
                        help="Continuar desde último checkpoint")
    parser.add_argument("--verbose", action="store_true",
                        help="Mostrar cada par procesado")
    args = parser.parse_args()

    print("=" * 60)
    print("  PIPELINE Xbox → Steam v1.0 (Invertido)")
    print("  Fuente: IGDB (catálogo Xbox) → Steam + Xbox IDs")
    print("=" * 60)

    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    ensure_tables(conn)
    conn.commit()

    # ── Checkpoint ──────────────────────────────────────────────
    checkpoint = conn.execute(
        "SELECT * FROM pipeline_checkpoint WHERE id = ?", (CHECKPOINT_ID,)
    ).fetchone()

    if args.resume and checkpoint and checkpoint["last_steam_app_id"]:
        try:
            offset = int(checkpoint["last_steam_app_id"])
        except (ValueError, TypeError):
            offset = 0
        print(f"  Resumiendo desde offset IGDB: {offset}")
    elif args.offset is not None:
        offset = args.offset
        print(f"  Offset inicial: {offset}")
    else:
        offset = 0
        print(f"  Offset inicial: {offset}")

    if args.limit > 0:
        print(f"  Límite: {args.limit} juegos IGDB")
    print()

    # ── Token IGDB ─────────────────────────────────────────────
    print("  🔑 Obteniendo token IGDB...")
    token = igdb_token()
    if not token:
        print("[FATAL] No se pudo autenticar con Twitch/IGDB.")
        conn.close()
        sys.exit(1)
    print(f"  ✅ Token OK\n")

    # ── Estadísticas ───────────────────────────────────────────
    stats = {
        "igdb_games_total": 0,
        "igdb_games_with_pairs": 0,
        "pairs_total": 0,
        "steam_price_ok": 0,
        "steam_price_fail": 0,
        "steam_free": 0,
        "xbox_price_ok": 0,
        "xbox_price_fail": 0,
        "xbox_free": 0,
        "xbox_gp": 0,
        "matches_stored": 0,
        "errors": 0,
    }

    start_time = time.time()
    processed_games = 0

    while True:
        if SHUTDOWN:
            break

        # ── Fase 1+2: Discovery ────────────────────────────────
        catalog = igdb_fetch_xbox_catalog(token, offset, PAGE_SIZE)

        if not catalog:
            print(f"\n  Fin del catálogo en offset {offset}. No hay más resultados.")
            break

        stats["igdb_games_total"] += len(catalog)
        batch_games_with_pairs = 0

        for game in catalog:
            if SHUTDOWN:
                break

            processed_games += 1
            igdb_game_id = game["igdb_game_id"]
            name = game["name"]
            steam_ids = game["steam_ids"]
            xbox_ids = game["xbox_ids"]

            if not steam_ids or not xbox_ids:
                continue

            batch_games_with_pairs += 1
            stats["igdb_games_with_pairs"] += 1

            # ── Primer match Steam × Xbox (sin producto cartesiano) ──
            matched = False
            for sid in steam_ids:
                if SHUTDOWN or matched:
                    break

                # ── Precio Steam (una sola vez por steam_id) ───
                sp = steam_price(sid)
                if not sp:
                    stats["steam_price_fail"] += 1
                    continue
                stats["steam_price_ok"] += 1

                if sp["is_free"]:
                    stats["steam_free"] += 1

                for xid in xbox_ids:
                    if SHUTDOWN or matched:
                        break

                    pair_id = f"{sid}↔{xid}"
                    stats["pairs_total"] += 1

                    try:
                        # ── Precio Xbox ────────────────────────
                        xp = xbox_price(xid)
                        if not xp:
                            stats["xbox_price_fail"] += 1
                            continue
                        stats["xbox_price_ok"] += 1

                        if xp.get("is_free"):
                            stats["xbox_free"] += 1
                        if xp.get("is_game_pass"):
                            stats["xbox_gp"] += 1

                        # ── Almacenar match ────────────────────
                        store_match_xbox(
                            conn, sid, name, sp, igdb_game_id, xid, xp
                        )
                        stats["matches_stored"] += 1
                        matched = True

                        if args.verbose:
                            gp_tag = " [GP]" if xp.get("is_game_pass") else ""
                            free_tag = " [FREE]" if sp["is_free"] or xp.get("is_free") else ""
                            print(
                                f"  [{processed_games:>4}] {name[:40]:40s} "
                                f"Steam:{sid:>10s} ${sp['price_usd']:.2f} USD "
                                f"↔ Xbox:{xid:>12s} ARS${xp['price_ars']:>8,.0f}"
                                f"{gp_tag}{free_tag}"
                            )

                    except Exception as e:
                        stats["errors"] += 1
                        if stats["errors"] <= 5:
                            print(f"  [ERROR] {pair_id}: {e}")

            # ── Commit periódico ───────────────────────────────
            if stats["matches_stored"] > 0 and stats["matches_stored"] % COMMIT_EVERY == 0:
                conn.commit()
                save_igdb_checkpoint(conn, offset, stats["igdb_games_total"])

                elapsed = time.time() - start_time
                rate = (
                    stats["igdb_games_total"] / elapsed * 60
                    if elapsed > 0
                    else 0
                )
                print(
                    f"  💾 [offset:{offset}] "
                    f"Games:{stats['igdb_games_total']:<5} "
                    f"Matches:{stats['matches_stored']:<4} "
                    f"S-OK:{stats['steam_price_ok']:<4} "
                    f"X-OK:{stats['xbox_price_ok']:<4} "
                    f"Pairs:{stats['pairs_total']:<5} "
                    f"Err:{stats['errors']:<2} "
                    f"| {rate:.0f}g/min"
                )

        # ── Commit de batch ─────────────────────────────────────
        conn.commit()
        save_igdb_checkpoint(conn, offset, stats["igdb_games_total"])

        elapsed = time.time() - start_time
        rate = (
            stats["igdb_games_total"] / elapsed * 60 if elapsed > 0 else 0
        )
        print(
            f"  📄 [offset:{offset}] "
            f"Batch:{len(catalog)} | w/pairs:{batch_games_with_pairs} | "
            f"Total games:{stats['igdb_games_total']} | "
            f"Matches:{stats['matches_stored']} | "
            f"{rate:.0f}g/min"
        )

        # ── Avanzar offset ─────────────────────────────────────
        offset += len(catalog)

        # ── Limite ─────────────────────────────────────────────
        if args.limit > 0 and stats["igdb_games_total"] >= args.limit:
            print(f"\n  Límite alcanzado ({args.limit} juegos IGDB).")
            break

    # ── Commit final ───────────────────────────────────────────────
    conn.commit()
    save_igdb_checkpoint(conn, offset, stats["igdb_games_total"])
    elapsed = time.time() - start_time

    # ── Resumen ─────────────────────────────────────────────────────
    print()
    print("=" * 60)
    print("  RESULTADOS — Xbox → Steam Pipeline v1.0")
    print("=" * 60)
    print(f"  Juegos IGDB consultados:   {stats['igdb_games_total']:>6}")
    print(f"  Juegos con pares S↔X:      {stats['igdb_games_with_pairs']:>6}")
    print(f"  Pares totales procesados:  {stats['pairs_total']:>6}")
    print(f"  Steam precio OK:           {stats['steam_price_ok']:>6}")
    print(f"  Steam sin precio:          {stats['steam_price_fail']:>6}")
    print(f"  Steam gratis:              {stats['steam_free']:>6}")
    print(f"  Xbox precio OK:            {stats['xbox_price_ok']:>6}")
    print(f"  Xbox sin precio:           {stats['xbox_price_fail']:>6}")
    print(f"  Xbox Game Pass:            {stats['xbox_gp']:>6}")
    print(f"  ✅ Nuevos matches:         {stats['matches_stored']:>6}")
    print(f"  ❌ Errores:                {stats['errors']:>6}")
    print(f"  ⏱️  Tiempo:                 {elapsed/60:.1f} min")

    # ── Top matches de este pipeline ────────────────────────────────
    match_count = conn.execute(
        "SELECT COUNT(*) FROM igdb_steam_to_xbox WHERE source = ?",
        (PIPELINE_SOURCE,),
    ).fetchone()[0]

    if match_count > 0:
        print(f"\n  Total matches xbox_steam_pipeline_v1 en DB: {match_count}")
        print(f"  Últimos 5 (más caros):")
        for r in conn.execute(
            """SELECT steam_app_id, xbox_title, steam_price_usd, xbox_price_ars,
                      xbox_is_game_pass
               FROM igdb_steam_to_xbox
               WHERE source = ? AND xbox_price_ars > 0
               ORDER BY xbox_price_ars DESC
               LIMIT 5""",
            (PIPELINE_SOURCE,),
        ).fetchall():
            gp = " [GP]" if r["xbox_is_game_pass"] else ""
            title = (r["xbox_title"] or f"Steam:{r['steam_app_id']}")[:40]
            print(
                f"    {title:40s} "
                f"${r['steam_price_usd']:>7.2f} USD ↔ "
                f"ARS${r['xbox_price_ars']:>10,.0f}{gp}"
            )

    conn.close()

    if SHUTDOWN:
        print(f"\n  ⏸️  Pipeline pausado. Progreso guardado en checkpoint id={CHECKPOINT_ID}.")
        print(f"  Reanudar: python xbox_steam_pipeline.py --resume")
    else:
        print(f"\n  ✅ Pipeline completado. Último offset: {offset}")


if __name__ == "__main__":
    main()