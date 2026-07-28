#!/usr/bin/env python3
"""
Limpia duplicados en igdb_steam_to_xbox.
Para cada steam_app_id con múltiples filas, conserva solo una.
Criterio: la fila con precio ARS > 0 más reciente, menor precio real si hay empate.
"""
import sqlite3
from pathlib import Path

DB_PATH = str(Path(__file__).resolve().parent.parent / "data" / "games.db")

def main():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row

    dupes = conn.execute("""
        SELECT steam_app_id, COUNT(*) as cnt
        FROM igdb_steam_to_xbox
        GROUP BY steam_app_id
        HAVING cnt > 1
        ORDER BY cnt DESC
    """).fetchall()

    if not dupes:
        print("No hay duplicados. Nada que hacer.")
        conn.close()
        return

    print(f"Encontrados {len(dupes)} steam_app_id con duplicados")

    deleted_total = 0
    affected_apps = []

    for row in dupes:
        app_id = row["steam_app_id"]
        count = row["cnt"]

        rows = conn.execute("""
            SELECT steam_game_id, steam_app_id, xbox_store_id, xbox_title,
                   xbox_price_ars, steam_price_usd, matched_at
            FROM igdb_steam_to_xbox
            WHERE steam_app_id = ?
            ORDER BY
                CASE WHEN xbox_price_ars > 0 AND steam_price_usd > 0 THEN 0 ELSE 1 END,
                matched_at DESC,
                xbox_price_ars ASC
        """, (app_id,)).fetchall()

        keeper = rows[0]
        to_delete = rows[1:]

        for dead in to_delete:
            conn.execute(
                "DELETE FROM igdb_steam_to_xbox WHERE steam_game_id = ? AND steam_app_id = ?",
                (dead["steam_game_id"], dead["steam_app_id"])
            )
            deleted_total += 1

        affected_apps.append({
            "app_id": app_id,
            "total_rows": count,
            "kept": keeper["xbox_store_id"],
            "deleted": len(to_delete),
            "title": keeper["xbox_title"],
        })

    conn.commit()
    conn.execute("VACUUM")
    conn.close()

    print(f"\nEliminados: {deleted_total} registros")
    print(f"Afectados: {len(affected_apps)} apps")
    print("\n── Detalle ──")
    for a in sorted(affected_apps, key=lambda x: x["deleted"], reverse=True)[:15]:
        print(f"  {a['app_id']}: {a['total_rows']}→1  | {a['title'][:45]}")


if __name__ == "__main__":
    main()