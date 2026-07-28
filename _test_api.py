import sys
sys.path.insert(0, 'scrapers')
from reverse_pipeline import fetch_xbox_price

ids = [('9MVXMVT8ZKWC', 'Minecraft'), ('9NKV34XDW014', 'Palworld'), ('C0N22P73QZ60', 'DBD')]
for pid, name in ids:
    r = fetch_xbox_price(pid)
    if r:
        print(f'{name}: ARS$ {r["list_price"]:,.2f} | Title: {r["title"]} | GP: {r["is_game_pass"]}')
    else:
        print(f'{name}: FAILED')
