"""
Game Price Comparison API — v2 (igdb_steam_to_xbox)
Flask REST endpoints serving matched Xbox AR vs Steam data.
"""
import sqlite3
from pathlib import Path

from flask import Flask, jsonify, request, send_from_directory
from flask_cors import CORS

DB_PATH = str(Path(__file__).parent.parent / "data" / "games.db")
FRONTEND_DIR = str(Path(__file__).parent.parent / "frontend")
PAGE_SIZE_MAX = 100

app = Flask(__name__, static_folder=FRONTEND_DIR, static_url_path="")
CORS(app)

import requests

try:
    r = requests.get("https://dolarapi.com/v1/dolares/oficial", timeout=5)
    r.raise_for_status()
    data = r.json()
    USD_ARS_RATE = data["venta"]
    USD_ARS_DATE = data.get("fechaActualizacion", "")
except Exception:
    USD_ARS_RATE = 1520  # Fallback: dolar oficial ~1520
    USD_ARS_DATE = ""


def get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def _build_filter_where(filter_param):
    """Build WHERE clause and params for filter param. Returns (where_clause, params_list)."""
    if not filter_param or filter_param == "all":
        return "WHERE i.xbox_price_ars > 0", []
    if filter_param == "gamepass":
        return "WHERE i.xbox_price_ars > 0 AND i.xbox_is_game_pass = 1", []
    if filter_param == "xbox-cheaper":
        return (
            f"WHERE i.xbox_price_ars > 0 AND ps.price > 0"
            f" AND ps.price > (i.xbox_price_ars / NULLIF({USD_ARS_RATE}, 0))",
            [],
        )
    if filter_param == "steam-cheaper":
        return (
            f"WHERE i.xbox_price_ars > 0 AND ps.price > 0"
            f" AND ps.price < (i.xbox_price_ars / NULLIF({USD_ARS_RATE}, 0))",
            [],
        )
    if filter_param == "discount":
        return (
            "WHERE i.xbox_price_ars > 0"
            " AND ((i.xbox_msrp_ars > i.xbox_price_ars AND i.xbox_is_game_pass = 0)"
            " OR ps.discount_percent > 0)",
            [],
        )
    return "WHERE i.xbox_price_ars > 0", []


def _build_row_dict(r):
    """Convert a sqlite3.Row from the games query into a game dict."""
    xbox_usd = round(r["xbox_price_ars"] / USD_ARS_RATE, 2) if r["xbox_price_ars"] > 0 else 0

    cheapest = None
    xbox_has_price = r["xbox_price_ars"] > 0
    steam_has_price = r["steam_price"] is not None and r["steam_price"] > 0
    if xbox_has_price and steam_has_price:
        cheapest = "xbox" if xbox_usd < r["steam_price"] else "steam"
    elif xbox_has_price:
        cheapest = "xbox"
    elif steam_has_price:
        cheapest = "steam"
    elif r["xbox_is_free"] and r["steam_free"]:
        cheapest = "both_free"
    elif r["xbox_is_free"]:
        cheapest = "xbox"
    elif r["steam_free"]:
        cheapest = "steam"

    xbox_msrp = r["xbox_msrp_ars"] or 0
    xbox_price = r["xbox_price_ars"] or 0
    xbox_original = xbox_msrp if xbox_msrp > xbox_price else xbox_price
    xbox_discount = round((xbox_msrp - xbox_price) / xbox_msrp * 100) if xbox_msrp > 0 and xbox_msrp > xbox_price else None

    return {
        "match_id": r["match_id"],
        "match_score": r["match_score"],
        "xbox": {
            "title": r["xbox_title"],
            "store_id": r["xbox_store_id"],
            "url": f"https://www.xbox.com/es-ar/games/store/-/{r['xbox_store_id']}" if r["xbox_store_id"] else None,
            "price_ars": xbox_price,
            "price_usd_equiv": xbox_usd,
            "original_price_ars": xbox_original,
            "discount_pct": xbox_discount,
            "is_game_pass": bool(r["xbox_is_game_pass"]),
            "is_free": bool(r["xbox_is_free"]),
        },
        "steam": {
            "id": r["steam_id"],
            "title": r["steam_title"] or r["xbox_title"],
            "steam_app_id": r["steam_app_id"],
            "url": r["steam_url"] or f"https://store.steampowered.com/app/{r['steam_app_id']}",
            "price_usd": r["steam_price"],
            "original_price_usd": r["steam_original_price"],
            "discount_pct": r["steam_discount"],
            "is_free": bool(r["steam_free"]) if r["steam_free"] is not None else False,
        },
        "cheapest": cheapest,
        "multiplier": r["multiplier"],
        "cheaper_on": r["cheaper_on"],
    }


@app.route("/api/metrics")
def metrics():
    """Dashboard A metrics with optional filter."""
    filter_param = request.args.get("filter", "all").strip()
    filter_where, _ = _build_filter_where(filter_param)

    conn = get_db()
    try:
        # comparable count
        comparable_count = conn.execute(
            f"SELECT COUNT(*) FROM igdb_steam_to_xbox i "
            "JOIN games gs ON gs.store_game_id = i.steam_app_id AND gs.store_id = 2 "
            "JOIN prices ps ON ps.game_id = gs.id "
            f"{filter_where}"
        ).fetchone()[0]

        # gamepass count
        gp_where, _ = _build_filter_where("gamepass")
        base_where, _ = _build_filter_where("all")
        gamepass_count = conn.execute(
            f"SELECT COUNT(*) FROM igdb_steam_to_xbox i "
            "JOIN games gs ON gs.store_game_id = i.steam_app_id AND gs.store_id = 2 "
            "JOIN prices ps ON ps.game_id = gs.id "
            f"{base_where} AND i.xbox_is_game_pass = 1"
        ).fetchone()[0]

        # % Xbox más barato: count rows where cheaper_on='xbox' / comparable * 100
        xbox_cheaper_count = conn.execute(
            f"SELECT COUNT(*) FROM igdb_steam_to_xbox i "
            "JOIN games gs ON gs.store_game_id = i.steam_app_id AND gs.store_id = 2 "
            "JOIN prices ps ON ps.game_id = gs.id "
            f"{filter_where} AND ps.price > 0 "
            f"AND ps.price > (i.xbox_price_ars / NULLIF({USD_ARS_RATE}, 0))"
        ).fetchone()[0]

        # Mediana diferencia en ARS:
        diffs = conn.execute(
            f"SELECT ABS(ps.price * {USD_ARS_RATE} - i.xbox_price_ars) as dif FROM igdb_steam_to_xbox i "
            "JOIN games gs ON gs.store_game_id = i.steam_app_id AND gs.store_id = 2 "
            "JOIN prices ps ON ps.game_id = gs.id "
            f"{filter_where} AND ps.price > 0 "
            "ORDER BY dif"
        ).fetchall()

        mediana = 0.0
        if diffs:
            n = len(diffs)
            if n % 2 == 1:
                mediana = diffs[n // 2][0]
            else:
                mediana = (diffs[n // 2 - 1][0] + diffs[n // 2][0]) / 2

        # Ahorro total potencial: SUM(MAX(xbox_usd, steam_price) - MIN(xbox_usd, steam_price))
        ahorro_total = conn.execute(
            f"SELECT SUM(MAX(ps.price * {USD_ARS_RATE}, i.xbox_price_ars) "
            f"- MIN(ps.price * {USD_ARS_RATE}, i.xbox_price_ars)) FROM igdb_steam_to_xbox i "
            "JOIN games gs ON gs.store_game_id = i.steam_app_id AND gs.store_id = 2 "
            "JOIN prices ps ON ps.game_id = gs.id "
            f"{filter_where}"
        ).fetchone()[0] or 0

        pct_xbox_mas_barato = round(xbox_cheaper_count / comparable_count * 100, 1) if comparable_count > 0 else 0

        return jsonify({
            "comparable": comparable_count,
            "gamepass": gamepass_count,
            "pct_xbox_mas_barato": pct_xbox_mas_barato,
            "ahorro_total_potencial": round(ahorro_total, 2),
            "mediana_diferencia_ars": round(mediana, 2),
            "usd_ars_rate": USD_ARS_RATE,
        })
    finally:
        conn.close()


@app.route("/api/featured")
def featured():
    """Secciones de juegos destacados: ofertas Xbox, ofertas Steam, mayor ahorro."""
    filter_param = request.args.get("filter", "all").strip()
    filter_where, _ = _build_filter_where(filter_param)
    limit = min(int(request.args.get("limit", 3)), 6)

    conn = get_db()
    try:
        sections = []

        # Sección 1 — 🔥 MEJORES OFERTAS XBOX (mayor % descuento, excluyendo Game Pass)
        rows = conn.execute(
            f"SELECT i.xbox_title, i.xbox_price_ars, i.xbox_msrp_ars, "
            f"ROUND((i.xbox_msrp_ars - i.xbox_price_ars) * 100.0 / NULLIF(i.xbox_msrp_ars,0), 1) as discount_pct, "
            f"i.xbox_store_id, "
            f"ps.price as steam_price, ps.discount_percent as steam_discount_pct, "
            f"ROUND(ps.price * {USD_ARS_RATE}, 0) as steam_price_ars "
            f"FROM igdb_steam_to_xbox i "
            f"JOIN games gs ON gs.store_game_id = i.steam_app_id AND gs.store_id = 2 "
            f"JOIN prices ps ON ps.game_id = gs.id "
            f"{filter_where} AND i.xbox_msrp_ars > i.xbox_price_ars AND i.xbox_is_game_pass = 0 "
            f"ORDER BY discount_pct DESC LIMIT {limit}"
        ).fetchall()

        games = []
        for r in rows:
            ahorro_ars = round(r[2] - r[1], 0)
            games.append({
                "xbox_title": r[0],
                "xbox_price_ars": r[1],
                "xbox_msrp_ars": r[2],
                "xbox_discount_pct": r[3],
                "xbox_store_id": r[4],
                "steam_price": r[5],
                "steam_discount_pct": r[6],
                "steam_price_ars": r[7],
                "ahorro_ars": ahorro_ars,
                "ahorro_pct": round(ahorro_ars * 100.0 / r[2], 1) if r[2] > 0 else 0,
            })
        sections.append({"id": "ofertas_xbox", "name": "🔥 MEJORES OFERTAS XBOX", "games": games})

        # Sección 2 — 💰 MEJORES OFERTAS STEAM (mayor % descuento)
        rows = conn.execute(
            f"SELECT i.xbox_title, i.xbox_price_ars, "
            f"ps.price as steam_price, ps.original_price, ps.discount_percent as steam_discount_pct, "
            f"ROUND(ps.price * {USD_ARS_RATE}, 0) as steam_price_ars "
            f"FROM igdb_steam_to_xbox i "
            f"JOIN games gs ON gs.store_game_id = i.steam_app_id AND gs.store_id = 2 "
            f"JOIN prices ps ON ps.game_id = gs.id "
            f"{filter_where} AND ps.discount_percent > 0 "
            f"ORDER BY ps.discount_percent DESC LIMIT {limit}"
        ).fetchall()

        games = []
        for r in rows:
            games.append({
                "xbox_title": r[0],
                "xbox_price_ars": r[1],
                "steam_price": r[2],
                "steam_original_price": r[3],
                "steam_discount_pct": r[4],
                "steam_price_ars": r[5],
                "ahorro_ars": round((r[3] - r[2]) * USD_ARS_RATE, 0),  # ahorro en ARS = (original - actual) * tasa
            })
        sections.append({"id": "ofertas_steam", "name": "💰 MEJORES OFERTAS STEAM", "games": games})

        # Sección 3 — 📊 JUEGOS COMPARADOS
        total = conn.execute(
            f"SELECT COUNT(*) FROM igdb_steam_to_xbox i "
            f"JOIN games gs ON gs.store_game_id = i.steam_app_id AND gs.store_id = 2 "
            f"JOIN prices ps ON ps.game_id = gs.id "
            f"{filter_where}"
        ).fetchone()[0]
        sections.append({"id": "juegos_comparados", "name": "📊 JUEGOS COMPARADOS", "games": [{"count": total}]})

        return jsonify({"sections": sections})
    finally:
        conn.close()


@app.route("/api/stats")
def stats():
    """Global stats: count, last update, summary."""
    conn = get_db()
    try:
        xbox_count = conn.execute(
            "SELECT COUNT(*) FROM games WHERE store_id = 1"
        ).fetchone()[0]
        steam_count = conn.execute(
            "SELECT COUNT(*) FROM games WHERE store_id = 2"
        ).fetchone()[0]

        # igdb_steam_to_xbox stats
        total_igdb = conn.execute(
            "SELECT COUNT(*) FROM igdb_steam_to_xbox WHERE xbox_store_id IS NOT NULL"
        ).fetchone()[0]
        with_price = conn.execute(
            "SELECT COUNT(*) FROM igdb_steam_to_xbox WHERE xbox_price_ars > 0"
        ).fetchone()[0]
        comparable = conn.execute("""
            SELECT COUNT(*) FROM igdb_steam_to_xbox i
            JOIN games gs ON gs.store_game_id = i.steam_app_id AND gs.store_id = 2
            JOIN prices ps ON ps.game_id = gs.id
            WHERE i.xbox_price_ars > 0
        """).fetchone()[0]

        last_xbox = conn.execute(
            "SELECT finished_at FROM scrape_log WHERE store_id = 1 AND status = 'completed' ORDER BY finished_at DESC LIMIT 1"
        ).fetchone()
        last_steam = conn.execute(
            "SELECT finished_at FROM scrape_log WHERE store_id = 2 AND status = 'completed' ORDER BY finished_at DESC LIMIT 1"
        ).fetchone()

        return jsonify(
            {
                "games": {
                    "xbox": xbox_count,
                    "steam": steam_count,
                    "matched": with_price,
                    "comparable": comparable,
                },
                "last_update": {
                    "xbox": last_xbox[0] if last_xbox else None,
                    "steam": last_steam[0] if last_steam else None,
                },
                "price_stats": {
                    "total_matches": with_price,
                    "comparable": comparable,
                },
                "usd_ars_rate": USD_ARS_RATE,
                "usd_ars_source": "dolarapi.com (oficial)",
            }
        )
    finally:
        conn.close()


@app.route("/api/games")
def games():
    """List all matched games with comparison via igdb_steam_to_xbox."""
    conn = get_db()
    try:
        q = request.args.get("q", "").strip()
        sort = request.args.get("sort", "title")
        order = request.args.get("order", "asc")
        filter_param = request.args.get("filter", "all").strip()
        limit = min(int(request.args.get("limit", 50)), PAGE_SIZE_MAX)
        offset = int(request.args.get("offset", 0))

        sort_map = {
            "title": "i.xbox_title",
            "xbox_price": "i.xbox_price_ars",
            "steam_price": "ps.price",
            "multiplier": "multiplier",
            "score": "i.steam_game_id",
        }
        sort_col = sort_map.get(sort, "i.xbox_title")
        order_clause = f"ORDER BY {sort_col} {'DESC' if order == 'desc' else 'ASC'}"

        where_base, params_base = _build_filter_where(filter_param)
        params = list(params_base)
        if q:
            where_base += " AND (i.xbox_title LIKE ? OR gs.title LIKE ?)"
            params.extend([f"%{q}%", f"%{q}%"])

        # COUNT(*) total for pagination
        total_count = conn.execute(
            f"SELECT COUNT(*) FROM igdb_steam_to_xbox i "
            "JOIN games gs ON gs.store_game_id = i.steam_app_id AND gs.store_id = 2 "
            "JOIN prices ps ON ps.game_id = gs.id "
            f"{where_base}", params
        ).fetchone()[0]

        query = f"""
            SELECT
                i.steam_game_id as match_id,
                i.steam_app_id,
                i.igdb_game_id,
                1.0 as match_score,
                i.xbox_store_id,
                i.xbox_title,
                i.xbox_price_ars,
                i.xbox_msrp_ars,
                i.xbox_wholesale_ars,
                i.xbox_is_game_pass,
                i.xbox_is_free,
                gs.id as steam_id,
                gs.title as steam_title,
                gs.store_game_id as steam_store_id,
                gs.url as steam_url,
                ps.price as steam_price,
                ps.original_price as steam_original_price,
                ps.discount_percent as steam_discount,
                ps.is_free as steam_free,
                CASE
                    WHEN i.xbox_price_ars > 0 AND ps.price > 0
                    THEN ROUND(MAX(ps.price, i.xbox_price_ars / NULLIF({USD_ARS_RATE}, 0)) / NULLIF(MIN(ps.price, i.xbox_price_ars / NULLIF({USD_ARS_RATE}, 0)), 0), 1)
                    ELSE NULL
                END as multiplier,
                CASE
                    WHEN i.xbox_price_ars > 0 AND ps.price > 0 AND ps.price > (i.xbox_price_ars / NULLIF({USD_ARS_RATE}, 0)) THEN 'xbox'
                    WHEN i.xbox_price_ars > 0 AND ps.price > 0 AND ps.price < (i.xbox_price_ars / NULLIF({USD_ARS_RATE}, 0)) THEN 'steam'
                    ELSE NULL
                END as cheaper_on
            FROM igdb_steam_to_xbox i
            JOIN games gs ON gs.store_game_id = i.steam_app_id AND gs.store_id = 2
            JOIN prices ps ON ps.game_id = gs.id
            {where_base}
            GROUP BY i.steam_app_id
            {order_clause}
            LIMIT ? OFFSET ?
        """
        params.extend([limit, offset])
        rows = conn.execute(query, params).fetchall()

        results = [_build_row_dict(r) for r in rows]

        pages = (total_count + limit - 1) // limit if total_count > 0 else 0

        return jsonify({"games": results, "total": total_count, "offset": offset, "limit": limit, "page": (offset // limit) + 1, "pages": pages})
    finally:
        conn.close()


@app.route("/api/game/<int:steam_game_id>")
def game_detail(steam_game_id):
    """Get single matched game with price history from igdb_steam_to_xbox."""
    conn = get_db()
    try:
        r = conn.execute("""
            SELECT
                i.steam_game_id as match_id,
                i.steam_app_id,
                i.igdb_game_id,
                i.xbox_store_id,
                i.xbox_title,
                i.xbox_price_ars,
                i.xbox_msrp_ars,
                i.xbox_wholesale_ars,
                i.xbox_is_game_pass,
                i.xbox_is_free,
                gs.id as steam_id,
                gs.title as steam_title,
                gs.store_game_id as steam_store_id,
                gs.url as steam_url,
                ps.price as steam_price,
                ps.original_price as steam_original_price,
                ps.discount_percent as steam_discount,
                ps.is_free as steam_free
            FROM igdb_steam_to_xbox i
            LEFT JOIN games gs ON gs.store_game_id = i.steam_app_id AND gs.store_id = 2
            LEFT JOIN prices ps ON ps.game_id = gs.id
            WHERE i.steam_game_id = ?
        """, (steam_game_id,)).fetchone()

        if not r:
            return jsonify({"error": "Match not found"}), 404

        xbox_usd = round(r["xbox_price_ars"] / USD_ARS_RATE, 2) if r["xbox_price_ars"] > 0 else 0

        return jsonify(
            {
                "match_id": r["match_id"],
                "match_score": 1.0,
                "xbox": {
                    "title": r["xbox_title"],
                    "store_id": r["xbox_store_id"],
                    "url": f"https://www.xbox.com/es-ar/games/store/-/{r['xbox_store_id']}" if r["xbox_store_id"] else None,
                    "price_ars": r["xbox_price_ars"],
                    "price_usd_equiv": xbox_usd,
                    "msrp_ars": r["xbox_msrp_ars"],
                    "wholesale_ars": r["xbox_wholesale_ars"],
                    "is_game_pass": bool(r["xbox_is_game_pass"]),
                    "is_free": bool(r["xbox_is_free"]),
                },
                "steam": {
                    "id": r["steam_id"],
                    "title": r["steam_title"] or r["xbox_title"],
                    "steam_app_id": r["steam_app_id"],
                    "url": r["steam_url"] or f"https://store.steampowered.com/app/{r['steam_app_id']}",
                    "price_usd": r["steam_price"],
                    "original_price_usd": r["steam_original_price"],
                    "discount_pct": r["steam_discount"],
                    "is_free": bool(r["steam_free"]) if r["steam_free"] is not None else False,
                },
            }
        )
    finally:
        conn.close()


@app.route("/api/search")
def search():
    """Search games across both stores. ?q=keyword&store=xbox|steam|all"""
    conn = get_db()
    try:
        q = request.args.get("q", "").strip()
        store_filter = request.args.get("store", "all")
        limit = min(int(request.args.get("limit", 20)), 100)

        if not q:
            return jsonify({"results": []})

        stores = []
        if store_filter in ("xbox", "all"):
            stores.append(1)
        if store_filter in ("steam", "all"):
            stores.append(2)

        placeholders = ",".join("?" * len(stores))
        query = f"""
            SELECT g.id, g.title, g.store_id, g.url, g.store_game_id,
                   p.price, p.original_price, p.discount_percent,
                   p.is_game_pass, p.is_free,
                   s.name as store_name, s.currency
            FROM games g
            JOIN prices p ON p.game_id = g.id
            JOIN stores s ON s.id = g.store_id
            WHERE g.store_id IN ({placeholders})
              AND g.title LIKE ?
            LIMIT ?
        """
        params = stores + [f"%{q}%", limit]
        rows = conn.execute(query, params).fetchall()

        results = []
        for r in rows:
            results.append(
                {
                    "id": r["id"],
                    "title": r["title"],
                    "store": r["store_name"],
                    "currency": r["currency"],
                    "url": r["url"],
                    "price": r["price"],
                    "original_price": r["original_price"],
                    "discount_pct": r["discount_percent"],
                    "is_game_pass": bool(r["is_game_pass"]),
                    "is_free": bool(r["is_free"]),
                }
            )

        return jsonify({"results": results})
    finally:
        conn.close()


@app.route("/")
def index():
    """Serve the SPA frontend."""
    return send_from_directory(FRONTEND_DIR, "index.html")


@app.route("/<path:path>")
def static_files(path):
    """Serve frontend static files (JS, CSS, etc.)."""
    return send_from_directory(FRONTEND_DIR, path)


@app.route("/api/config")
def api_config():
    """Return client configuration including live exchange rate."""
    return jsonify(
        {
            "usd_ars_rate": USD_ARS_RATE,
            "usd_ars_date": USD_ARS_DATE,
            "usd_ars_source": "dolarapi.com (oficial)",
            "stores": ["xbox", "steam"],
        }
    )


if __name__ == "__main__":
    print(f"Starting Game Price Comparison API v2 on http://localhost:5000")
    print(f"DB: {DB_PATH}")
    app.run(debug=True, host="0.0.0.0", port=5000)