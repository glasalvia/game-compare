#!/usr/bin/env python3
import sqlite3, json

conn = sqlite3.connect('/home/glasalvia/.openclaw/workspace/game-compare/data/games.db')
c = conn.cursor()

report = {}

# scrape log
c.execute("SELECT status, store_id, started_at, finished_at, games_added, games_updated FROM scrape_log ORDER BY finished_at DESC LIMIT 10")
report["scrape_log"] = []
for r in c.fetchall():
    report["scrape_log"].append({"status": r[0], "store_id": r[1], "started": str(r[2]), "finished": str(r[3]), "added": r[4], "updated": r[5]})

# steam price breakdown
c.execute("SELECT CASE WHEN price>0 THEN 'paid' WHEN is_free=1 THEN 'free' ELSE 'zero_price' END as cat, COUNT(*) as n FROM games g JOIN prices p ON p.game_id=g.id WHERE g.store_id=2 GROUP BY cat")
report["price_breakdown"] = {r[0]: r[1] for r in c.fetchall()}

# paid stats
c.execute("SELECT AVG(price), MIN(price), MAX(price), COUNT(*) FROM games g JOIN prices p ON p.game_id=g.id WHERE g.store_id=2 AND price>0")
r = c.fetchone()
report["paid_stats"] = {"avg": round(float(r[0]), 2), "min": r[1], "max": r[2], "count": r[3]}

# date range
c.execute("SELECT MIN(scraped_at), MAX(scraped_at) FROM prices WHERE game_id IN (SELECT id FROM games WHERE store_id=2)")
r = c.fetchone()
report["price_dates"] = {"min": str(r[0]), "max": str(r[1])}

# sample paid
c.execute("SELECT g.title, p.price, p.is_free, p.scraped_at FROM games g JOIN prices p ON p.game_id=g.id WHERE g.store_id=2 AND p.price>0 ORDER BY g.title LIMIT 10")
report["sample_paid"] = [{"title": r[0], "price": r[1], "is_free": r[2], "scraped": str(r[3])} for r in c.fetchall()]

# sample zero not free
c.execute("SELECT g.title, p.price, p.is_free, p.scraped_at FROM games g JOIN prices p ON p.game_id=g.id WHERE g.store_id=2 AND p.price=0 AND p.is_free=0 ORDER BY g.title LIMIT 10")
report["sample_zero"] = [{"title": r[0], "price": r[1], "is_free": r[2], "scraped": str(r[3])} for r in c.fetchall()]

# total counts
c.execute("SELECT store_id, COUNT(*) FROM games GROUP BY store_id")
report["games_count"] = {str(r[0]): r[1] for r in c.fetchall()}

# Xbox (store=1) price check
c.execute("SELECT CASE WHEN price>0 THEN 'paid' WHEN is_free=1 THEN 'free' ELSE 'zero_price' END, COUNT(*) FROM games g JOIN prices p ON p.game_id=g.id WHERE g.store_id=1 GROUP BY 1")
report["xbox_price_breakdown"] = {r[0]: r[1] for r in c.fetchall()}

# IGDB table counts
c.execute("SELECT COUNT(*) FROM igdb_steam_to_xbox WHERE xbox_price_ars > 0")
report["igdb_with_price"] = c.fetchone()[0]
c.execute("SELECT COUNT(*) FROM igdb_steam_to_xbox WHERE xbox_store_id IS NOT NULL")
report["igdb_with_xbox_id"] = c.fetchone()[0]

conn.close()

with open('/home/glasalvia/.openclaw/workspace/game-compare/scratch/diag_report.json', 'w') as f:
    json.dump(report, f, indent=2, ensure_ascii=False)

print("Report written successfully")