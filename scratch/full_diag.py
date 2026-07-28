#!/usr/bin/env python3
"""Complete diagnosis of Steam prices in Game Compare DB."""
import sqlite3, json, sys, os

sys.path.insert(0, '/home/glasalvia/.openclaw/workspace/game-compare')
os.chdir('/home/glasalvia/.openclaw/workspace/game-compare')
conn = sqlite3.connect('data/games.db')
c = conn.cursor()
OUT = []

def report(section, *lines):
    OUT.append(f"\n=== {section} ===")
    for l in lines:
        OUT.append(str(l))

# 1. Overall breakdown
c.execute("SELECT CASE WHEN p.price>0 THEN 'PAID' WHEN p.is_free=1 THEN 'FREE' ELSE 'ZERO_NOT_FREE' END, COUNT(*) FROM games g JOIN prices p ON p.game_id=g.id WHERE g.store_id=2 GROUP BY 1")
report("PRICE BREAKDOWN (store_id=2)", *[f"{r[0]}: {r[1]}" for r in c.fetchall()])

# 2. Scrape dates
c.execute("SELECT MIN(scraped_at), MAX(scraped_at) FROM prices WHERE game_id IN (SELECT id FROM games WHERE store_id=2)")
r = c.fetchone()
report("PRICE DATE RANGE", f"From: {r[0]}", f"To: {r[1]}")

# 3. Check the 89 comparable games in detail
c.execute("""
    SELECT i.steam_app_id, i.xbox_title, i.xbox_price_ars,
           gs.id as steam_db_id, gs.title as steam_title, gs.store_game_id,
           ps.price as steam_price, ps.original_price, ps.is_free,
           ps.scraped_at
    FROM igdb_steam_to_xbox i
    LEFT JOIN games gs ON gs.store_game_id = i.steam_app_id AND gs.store_id = 2
    LEFT JOIN prices ps ON ps.game_id = gs.id
    WHERE i.xbox_price_ars > 0
    GROUP BY i.steam_app_id
    ORDER BY i.xbox_title
    LIMIT 30
""")
report("FIRST 30 COMPARABLE GAMES (API view)", *[f"{r[1]:40s} | Steam: ${r[6]} | Xbox: ${r[2]} ARS | is_free={r[8]} | steam_db_id={r[3]}" for r in c.fetchall()])

# 4. Games where Steam price shows as 0/None in the API
c.execute("""
    SELECT i.steam_app_id, i.xbox_title, i.xbox_price_ars,
           gs.price as steam_price_raw
    FROM igdb_steam_to_xbox i
    LEFT JOIN (SELECT g.store_game_id, p.price FROM games g JOIN prices p ON p.game_id=g.id WHERE g.store_id=2) gs
      ON gs.store_game_id = i.steam_app_id
    WHERE i.xbox_price_ars > 0
      AND (gs.price IS NULL OR gs.price = 0)
    GROUP BY i.steam_app_id
    LIMIT 30
""")
report("COMPARABLE GAMES WITH STEAM PRICE = 0 or NULL", *[f"app_id={r[0]} | {r[1]:40s} | Xbox:{r[2]} ARS | Steam raw={r[3]}" for r in c.fetchall()])

# 5. Count how many of the 177 have actual steam price > 0
c.execute("""
    SELECT COUNT(*)
    FROM igdb_steam_to_xbox i
    JOIN games gs ON gs.store_game_id = i.steam_app_id AND gs.store_id = 2
    JOIN prices ps ON ps.game_id = gs.id
    WHERE i.xbox_price_ars > 0 AND ps.price > 0
""")
report("IGDB with BOTH prices > 0", f"Count: {c.fetchone()[0]}")

# 6. Count how many of 177 have steam_price = 0 or null
c.execute("""
    SELECT CASE 
        WHEN gs.id IS NULL THEN 'NO_STEAM_DB_ENTRY'
        WHEN ps.price IS NULL THEN 'PRICE_NULL'
        WHEN ps.price = 0 AND ps.is_free = 1 THEN 'FREE (correct)'
        WHEN ps.price = 0 AND ps.is_free = 0 THEN 'ZERO_NOT_FREE (issue!)'
        ELSE 'OK'
    END as status, COUNT(*)
    FROM igdb_steam_to_xbox i
    LEFT JOIN games gs ON gs.store_game_id = i.steam_app_id AND gs.store_id = 2
    LEFT JOIN prices ps ON ps.game_id = gs.id
    WHERE i.xbox_price_ars > 0
    GROUP BY status
""")
report("COMPARABLE GAMES STATUS", *[f"{r[0]}: {r[1]}" for r in c.fetchall()])

# 7. For ZERO_NOT_FREE games, check if they exist with a real price elsewhere
c.execute("""
    SELECT g.title, g.store_game_id, p.price, p.is_free
    FROM games g 
    JOIN prices p ON p.game_id = g.id
    WHERE g.store_id = 2 
    AND g.title LIKE 'A Castle Full of Cats'
""")
report("SAMPLE: A Castle Full of Cats in DB", *[f"{r}" for r in c.fetchall()])

c.execute("""
    SELECT g.title, g.store_game_id, g.id, p.price, p.is_free
    FROM games g 
    JOIN prices p ON p.game_id = g.id
    WHERE g.store_id = 2 
    AND g.title LIKE '%Stardew%'
""")
report("SAMPLE: Stardew Valley in DB", *[f"{r}" for r in c.fetchall()])

c.execute("""
    SELECT g.title, g.store_game_id, g.id, p.price, p.is_free
    FROM games g 
    JOIN prices p ON p.game_id = g.id
    WHERE g.store_id = 2 
    AND g.title LIKE '%Vampire Survivors%'
""")
report("SAMPLE: Vampire Survivors in DB", *[f"{r}" for r in c.fetchall()])

# 8. Check IGDB steam_app_id format vs games.store_game_id format
c.execute("SELECT store_game_id FROM games WHERE store_id=2 AND title LIKE 'A Castle Full of Cats'")
report("GAMES: A Castle Full of Cats store_game_id", *[str(r[0]) for r in c.fetchall()])

c.execute("SELECT steam_app_id FROM igdb_steam_to_xbox WHERE xbox_title LIKE 'A Castle Full of Cats'")
report("IGDB: A Castle Full of Cats steam_app_id", *[str(r[0]) for r in c.fetchall()])

# 9. Check if steam_app_id format issue
c.execute("SELECT steam_app_id, CAST(steam_app_id AS TEXT) FROM igdb_steam_to_xbox WHERE xbox_title LIKE 'A Castle Full of Cats'")
report("IGDB APP ID TYPE CHECK", *[f"raw={r[0]}, cast={r[1]}" for r in c.fetchall()])

c.execute("SELECT store_game_id, typeof(store_game_id) FROM games WHERE store_id=2 AND title LIKE 'A Castle Full of Cats'")
report("GAMES STORE_GAME_ID TYPE CHECK", *[f"raw={r[0]}, type={r[1]}" for r in c.fetchall()])

# Write everything
with open('scratch/full_diagnosis.txt', 'w') as f:
    f.write('\n'.join(OUT))
print(f"Wrote {len(OUT)} lines to scratch/full_diagnosis.txt")
conn.close()