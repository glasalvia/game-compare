#!/usr/bin/env python3
"""
Pipeline Steam ↔ Xbox v3.0 — Steam ↔ Xbox con precios de APIs autoritativas.

Flujo:
  1. Toma IDs de steam_queue (o todos los Steam con match IGDB si no hay queue)
  2. Steam API → precio USD (JSON estructurado, cero ambigüedad)
  3. IGDB → Xbox store IDs (puente de matching cross-platform)
  4. Xbox Display Catalog API → precio ARS (JSON estructurado)
  5. INSERT en igdb_steam_to_xbox + games + prices (solo si ambos precios > 0)

Principios:
  - Cero scraping HTML. Ambas fuentes de precio son APIs JSON.
  - Solo se almacenan juegos con match confirmado y precios válidos.
  - Idempotente: skips juegos ya procesados.
  - Respetuoso de rate limits: Steam API (~1 req/s), IGDB (3.5 req/s), Xbox (6 req/s).
  - Commit cada N procesados. Resumible (Ctrl+C guarda progreso).

Uso:
  python steam_xbox_pipeline.py              # Procesa steam_queue completa
  python steam_xbox_pipeline.py --limit 50   # Procesa solo 50 juegos
  python steam_xbox_pipeline.py --resume     # Continúa desde último checkpoint
"""

import argparse
import re
import signal
import sqlite3
import sys
import time

from scrapers._api_helpers import (
    DB_PATH, STEAM_API, IGDB_API, TWITCH_AUTH, XBOX_API,
    STEAM_DELAY, IGDB_DELAY, XBOX_DELAY, MAX_RETRIES,
    igdb_token, igdb_call, steam_price, xbox_price,
    ensure_game, upsert_price, store_match, save_checkpoint,
)

COMMIT_EVERY = 25         # Guardar DB cada N juegos

# Control de interrupción
SHUTDOWN = False

def _handle_signal(sig, frame):
    global SHUTDOWN
    print("\n⏸️  Interrupción detectada. Guardando progreso...")
    SHUTDOWN = True

signal.signal(signal.SIGINT, _handle_signal)
signal.signal(signal.SIGTERM, _handle_signal)


# ── API Helpers (local) ─────────────────────────────────────────────


def igdb_find_xbox(token, steam_app_id):
    """Steam app_id → IGDB game → Xbox store IDs (12-char alphanumeric)."""
    # Paso 1: IGDB game ID
    results = igdb_call(token, "external_games",
                       f'where uid="{steam_app_id}"; fields game; limit 1;')
    if not results:
        return None, []
    
    igdb_game_id = results[0].get("game")
    if not igdb_game_id:
        return None, []
    
    # Paso 2: Xbox store IDs
    results = igdb_call(token, "external_games",
                       f'where game={igdb_game_id}; fields uid; limit 50;')
    
    XBOX_ID_RE = re.compile(r'^[A-Z0-9]{12}$')
    xbox_ids = [r["uid"] for r in results 
                if r.get("uid") and XBOX_ID_RE.match(r["uid"])]
    
    return igdb_game_id, xbox_ids


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
        
        CREATE TABLE IF NOT EXISTS steam_queue (
            steam_app_id TEXT PRIMARY KEY,
            added_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            processed_at TIMESTAMP,
            status TEXT DEFAULT 'pending'
        );
        
        CREATE TABLE IF NOT EXISTS pipeline_checkpoint (
            id INTEGER PRIMARY KEY CHECK (id = 1),
            last_steam_app_id TEXT,
            processed_count INTEGER DEFAULT 0,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );
        INSERT OR IGNORE INTO pipeline_checkpoint (id) VALUES (1);
    """)


# ── Main Pipeline ───────────────────────────────────────────────────

def mark_queue_processed(conn, steam_app_id, status='done'):
    """Marca un ID de steam_queue como procesado."""
    conn.execute("""
        UPDATE steam_queue 
        SET processed_at = CURRENT_TIMESTAMP, status = ?
        WHERE steam_app_id = ?
    """, (status, steam_app_id))


def main():
    parser = argparse.ArgumentParser(description="Pipeline Steam ↔ Xbox v3.0")
    parser.add_argument("--limit", type=int, default=0,
                        help="Procesar solo N juegos")
    parser.add_argument("--resume", action="store_true",
                        help="Continuar desde último checkpoint")
    parser.add_argument("--verbose", action="store_true",
                        help="Mostrar cada juego procesado")
    args = parser.parse_args()
    
    print("=" * 60)
    print("  PIPELINE Steam ↔ Xbox v3.0")
    print("  APIs: Steam (JSON) + IGDB (match) + Xbox (JSON)")
    print("=" * 60)
    
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    ensure_tables(conn)
    conn.commit()
    
    # ── Obtener juegos a procesar ──────────────────────────────
    checkpoint = conn.execute("SELECT * FROM pipeline_checkpoint WHERE id=1").fetchone()
    
    # Prioridad 1: steam_queue pendiente
    # Prioridad 2: Steam games sin match en igdb_steam_to_xbox
    queue_count = conn.execute(
        "SELECT COUNT(*) FROM steam_queue WHERE status='pending'"
    ).fetchone()[0]
    
    if queue_count > 0:
        print(f"\n  steam_queue pendiente: {queue_count}")
        query = """
            SELECT sq.steam_app_id, g.title
            FROM steam_queue sq
            LEFT JOIN games g ON g.store_game_id = sq.steam_app_id AND g.store_id = 2
            WHERE sq.status = 'pending'
            ORDER BY sq.added_at
        """
    else:
        # Fallback: Steam games sin match (si steam_queue está vacía)
        print("  steam_queue vacía. Buscando Steam sin match...")
        query = """
            SELECT g.store_game_id as steam_app_id, g.title
            FROM games g
            WHERE g.store_id = 2
            AND g.store_game_id NOT IN (
                SELECT steam_app_id FROM igdb_steam_to_xbox
            )
            ORDER BY g.id
        """
    
    if args.resume and checkpoint and checkpoint["last_steam_app_id"]:
        resume_id = checkpoint["last_steam_app_id"]
        query += f" AND (sq.steam_app_id > '{resume_id}' OR g.store_game_id > '{resume_id}')"
        print(f"  Resumiendo desde: {resume_id}")
    
    if args.limit > 0:
        query += f" LIMIT {args.limit}"
    
    games = conn.execute(query).fetchall()
    total = len(games)
    print(f"  Juegos a procesar: {total}\n")
    
    if total == 0:
        print("  Nada que procesar.")
        conn.close()
        return
    
    # ── Token IGDB ─────────────────────────────────────────────
    token = igdb_token()
    if not token:
        print("[FATAL] No se pudo autenticar con Twitch/IGDB.")
        conn.close()
        sys.exit(1)
    
    # ── Estadísticas ───────────────────────────────────────────
    stats = {
        "total": total,
        "steam_price_ok": 0,
        "steam_price_fail": 0,
        "igdb_found": 0,
        "igdb_miss": 0,
        "xbox_match": 0,
        "xbox_miss": 0,
        "xbox_price_ok": 0,
        "xbox_price_fail": 0,
        "matches_stored": 0,
        "free_steam": 0,
        "free_xbox": 0,
        "gp_xbox": 0,
        "errors": 0,
        "processed": 0,
    }
    
    start_time = time.time()
    last_steam_id = None
    
    for i, game in enumerate(games):
        if SHUTDOWN:
            break
        
        steam_app_id = game["steam_app_id"]
        steam_title = game["title"] or f"Steam:{steam_app_id}"
        last_steam_id = steam_app_id
        
        stats["processed"] += 1
        
        try:
            # ── Paso 1: Precio Steam (API) ──────────────────
            sp = steam_price(steam_app_id)
            if not sp:
                stats["steam_price_fail"] += 1
                mark_queue_processed(conn, steam_app_id, 'no_steam_price')
                continue
            stats["steam_price_ok"] += 1
            
            if sp["is_free"]:
                stats["free_steam"] += 1
            
            # ── Paso 2: IGDB → Xbox IDs ──────────────────────
            igdb_game_id, xbox_ids = igdb_find_xbox(token, steam_app_id)
            
            if igdb_game_id is None:
                stats["igdb_miss"] += 1
                mark_queue_processed(conn, steam_app_id, 'no_igdb_match')
                continue
            stats["igdb_found"] += 1
            
            if not xbox_ids:
                stats["xbox_miss"] += 1
                mark_queue_processed(conn, steam_app_id, 'no_xbox_match')
                continue
            stats["xbox_match"] += len(xbox_ids)
            
            # ── Paso 3: Precio Xbox (API) ─────────────────────
            xbox_id = xbox_ids[0]  # primer Xbox ID (más relevante)
            xp = xbox_price(xbox_id)
            
            if not xp:
                stats["xbox_price_fail"] += 1
                mark_queue_processed(conn, steam_app_id, 'no_xbox_price')
                continue
            stats["xbox_price_ok"] += 1
            
            if xp.get("is_free"):
                stats["free_xbox"] += 1
            if xp.get("is_game_pass"):
                stats["gp_xbox"] += 1
            
            # ── Paso 4: Almacenar ──────────────────────────────
            store_match(conn, steam_app_id, steam_title, sp, 
                       igdb_game_id, xbox_id, xp)
            stats["matches_stored"] += 1
            mark_queue_processed(conn, steam_app_id, 'done')
            
            if args.verbose:
                gp_tag = " [GP]" if xp.get("is_game_pass") else ""
                free_tag = " [FREE]" if sp["is_free"] or xp.get("is_free") else ""
                print(
                    f"  [{i+1:>4}/{total}] {steam_title[:40]:40s} "
                    f"${sp['price_usd']:.2f} USD → ARS${xp['price_ars']:,.0f}"
                    f"{gp_tag}{free_tag}"
                )
        
        except Exception as e:
            stats["errors"] += 1
            if stats["errors"] <= 5:
                print(f"  [ERROR] {steam_title[:40]}: {e}")
            mark_queue_processed(conn, steam_app_id, 'error')
        
        # ── Commit periódico ───────────────────────────────────
        if stats["processed"] % COMMIT_EVERY == 0:
            conn.commit()
            save_checkpoint(conn, last_steam_id, stats["processed"])
            
            elapsed = time.time() - start_time
            rate = stats["processed"] / elapsed * 60 if elapsed > 0 else 0
            eta = (total - stats["processed"]) / rate if rate > 0 else 0
            print(
                f"  💾 [{stats['processed']:>4}/{total}] "
                f"Matches:{stats['matches_stored']:<4} "
                f"SteamOK:{stats['steam_price_ok']:<4} "
                f"IGDB:{stats['igdb_found']:<4} "
                f"XboxOK:{stats['xbox_price_ok']:<4} "
                f"Err:{stats['errors']:<2} "
                f"| {rate:.0f}/min | ETA:{eta:.0f}min"
            )
    
    # ── Commit final ───────────────────────────────────────────────
    conn.commit()
    if last_steam_id:
        save_checkpoint(conn, last_steam_id, stats["processed"])
    elapsed = time.time() - start_time
    
    # ── Quick audit: ¿algún match tiene Steam price = 0 sin ser free? ──
    zero_price_issues = conn.execute("""
        SELECT COUNT(*) FROM igdb_steam_to_xbox 
        WHERE steam_price_usd = 0 AND steam_is_free = 0
    """).fetchone()[0]
    
    # ── Resumen ─────────────────────────────────────────────────────
    print()
    print("=" * 60)
    print("  RESULTADOS")
    print("=" * 60)
    print(f"  Procesados:           {stats['processed']:>6}")
    print(f"  Steam precio OK:      {stats['steam_price_ok']:>6}")
    print(f"  Steam sin precio:     {stats['steam_price_fail']:>6}")
    print(f"  Steam gratis:         {stats['free_steam']:>6}")
    print(f"  IGDB encontrados:     {stats['igdb_found']:>6}")
    print(f"  IGDB sin match:       {stats['igdb_miss']:>6}")
    print(f"  Xbox IDs:             {stats['xbox_match']:>6}")
    print(f"  Xbox sin IDs:         {stats['xbox_miss']:>6}")
    print(f"  Xbox precio OK:       {stats['xbox_price_ok']:>6}")
    print(f"  Xbox sin precio:      {stats['xbox_price_fail']:>6}")
    print(f"  Xbox Game Pass:       {stats['gp_xbox']:>6}")
    print(f"  ✅ Nuevos matches:    {stats['matches_stored']:>6}")
    print(f"  ❌ Errores:           {stats['errors']:>6}")
    print(f"  ⚠️  Zero-price audit:   {zero_price_issues:>6}")
    print(f"  ⏱️  Tiempo:            {elapsed/60:.1f} min")
    
    # ── Precios sospechosos ─────────────────────────────────────────
    if zero_price_issues > 0:
        print(f"\n  ⚠️  {zero_price_issues} juegos con price=0 pero NO marcados free:")
        for r in conn.execute("""
            SELECT steam_app_id, xbox_price_ars 
            FROM igdb_steam_to_xbox 
            WHERE steam_price_usd = 0 AND steam_is_free = 0 
            LIMIT 10
        """).fetchall():
            print(f"    Steam:{r['steam_app_id']} | Xbox:ARS${r['xbox_price_ars']:,.0f}")
    
    # ── Top nuevos matches ──────────────────────────────────────────
    print(f"\n  Últimos 5 matches (más caros):")
    for r in conn.execute("""
        SELECT steam_app_id, xbox_title, steam_price_usd, xbox_price_ars, xbox_is_game_pass
        FROM igdb_steam_to_xbox
        WHERE xbox_price_ars > 0 AND source = 'definitive_pipeline_v3'
        ORDER BY xbox_price_ars DESC
        LIMIT 5
    """).fetchall():
        gp = " [GP]" if r["xbox_is_game_pass"] else ""
        title = (r["xbox_title"] or f"Steam:{r['steam_app_id']}")[:40]
        print(f"    {title:40s} ${r['steam_price_usd']:>7.2f} USD ↔ ARS${r['xbox_price_ars']:>10,.0f}{gp}")
    
    conn.close()
    
    if SHUTDOWN:
        print(f"\n  ⏸️  Pipeline pausado. Progreso guardado en checkpoint y steam_queue.")
        print(f"  Reanudar: python steam_xbox_pipeline.py --resume")
    else:
        print(f"\n  ✅ Pipeline completado.")
        queue_remaining = sqlite3.connect(DB_PATH).execute(
            "SELECT COUNT(*) FROM steam_queue WHERE status='pending'"
        ).fetchone()[0]
        if queue_remaining > 0:
            print(f"  📋 steam_queue pendiente: {queue_remaining}")
            print(f"  Re-ejecutar: python steam_xbox_pipeline.py --limit 100")


if __name__ == "__main__":
    main()
