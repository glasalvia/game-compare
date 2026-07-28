#!/bin/bash
# ─── Game Compare: Verificación de precios y mantenimiento ───
# El definitive_pipeline.py ya verifica precios al insertar (price_verified=1).
# Este script es mantenimiento: auditoría de DB, zero-price, y reporte.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$SCRIPT_DIR/.."

LOG_DIR="logs"
mkdir -p "$LOG_DIR"
TS=$(date +%Y%m%d_%H%M)
LOG="$LOG_DIR/verify_${TS}.log"

{
    echo "=== Game Compare — Auditoría de precios ==="
    echo "Inicio: $(date)"
    echo ""

    # ── Reporte de métricas ──
    echo "─── MÉTRICAS ───"
    sqlite3 data/games.db "
    SELECT 'Steam juegos:      ' || COUNT(*) FROM games WHERE store_id=2;
    SELECT 'Xbox juegos:       ' || COUNT(*) FROM games WHERE store_id=1;
    SELECT 'Steam verificados: ' || COUNT(*) FROM prices p 
    JOIN games g ON g.id=p.game_id WHERE g.store_id=2 AND p.price_verified=1;
    SELECT 'Xbox verificados:  ' || COUNT(*) FROM prices p 
    JOIN games g ON g.id=p.game_id WHERE g.store_id=1 AND p.price_verified=1;
    SELECT 'Steam pendientes:  ' || COUNT(*) FROM prices p 
    JOIN games g ON g.id=p.game_id WHERE g.store_id=2 AND (p.price_verified=0 OR p.price_verified IS NULL);
    SELECT 'Xbox pendientes:   ' || COUNT(*) FROM prices p 
    JOIN games g ON g.id=p.game_id WHERE g.store_id=1 AND (p.price_verified=0 OR p.price_verified IS NULL);
    SELECT 'Matches totales:   ' || COUNT(*) FROM igdb_steam_to_xbox;
    SELECT 'Matches con precio:' || COUNT(*) FROM igdb_steam_to_xbox WHERE xbox_price_ars > 0;
    SELECT 'Zero-price steam:  ' || COUNT(*) FROM igdb_steam_to_xbox i
    JOIN prices p ON p.game_id=i.steam_game_id WHERE p.price=0 AND p.is_free=0;
    SELECT 'Queue pendiente:   ' || COUNT(*) FROM steam_queue WHERE status='pending';
    "

    echo ""
    echo "─── TOP 10 — Mayor multiplicador ARS/USD ───"
    sqlite3 -header -column data/games.db "
    SELECT i.xbox_title AS 'Xbox',
           printf('$%.2f', i.steam_price_usd) AS 'Steam_USD',
           printf('ARS$%.0f', i.xbox_price_ars) AS 'Xbox_ARS',
           printf('%.1fx', i.xbox_price_ars / i.steam_price_usd) AS 'Multiplier'
    FROM igdb_steam_to_xbox i
    WHERE i.steam_price_usd > 0 AND i.xbox_price_ars > 0
    ORDER BY (i.xbox_price_ars / i.steam_price_usd) DESC
    LIMIT 10;
    "

    echo ""
    echo "Fin: $(date)"
} 2>&1 | tee -a "$LOG"

# Limpiar logs viejos (>30 días)
find "$LOG_DIR" -name "verify_*.log" -mtime +30 -delete 2>/dev/null || true