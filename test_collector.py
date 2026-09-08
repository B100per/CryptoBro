import sqlite3

import collector
from collector import build_row, top_symbols

prem = {"symbol": "BTCUSDT", "markPrice": "80641.2", "lastFundingRate": "0.00005852"}
tick = {"symbol": "BTCUSDT", "quoteVolume": "9.0e9"}
oi = {"sumOpenInterest": "112379.323", "sumOpenInterestValue": "9064538529.79"}
ratio = {"longShortRatio": "0.9026"}
taker = {"buySellRatio": "0.8789", "buyVol": "157.574", "sellVol": "179.279"}

row = build_row(1788503700000, "BTCUSDT", prem, tick, oi, ratio, ratio, ratio, taker)
assert len(row) == 13 and row[:2] == (1788503700000, "BTCUSDT")
assert row[3] == 0.00005852 and row[5] == 112379.323 and row[10] == 0.8789

tickers = [
    {"symbol": "ETHUSDT", "quoteVolume": "5"},
    {"symbol": "BTCUSDT", "quoteVolume": "9"},
    {"symbol": "BTCUSDT_260327", "quoteVolume": "99"},  # delivery, excluded
    {"symbol": "BTCUSDC", "quoteVolume": "99"},          # not USDT, excluded
]
assert top_symbols(tickers, n=1) == ["BTCUSDT"]
assert top_symbols(tickers) == ["BTCUSDT", "ETHUSDT"]

# a fractional day (what heal asks for) must still send an integer startTime:
# Binance answers a float with 400 Bad Request, and the first boot did exactly that
seen = []
collector.get = lambda path, base=None, **q: seen.append(q) or []
db0 = sqlite3.connect(":memory:")
db0.execute(collector.SCHEMA_TH)
collector.save_klines(db0, "BTCUSDT", days=0.76, base=collector.TH_BASE, table="th_klines")
assert isinstance(seen[0]["startTime"], int), seen

# heal: a fresh database needs nothing; a whole week needs nothing; a hole in
# the middle (a refill that failed) and one at the end (the PC was off) are
# both refilled from the oldest empty slot, through both collectors
calls = []
collector.collect_th = lambda db, days=None: calls.append(("th", days))
collector.collect_once = lambda db, history_days=None: calls.append(("fut", history_days))
P = collector.PERIOD_MS
now = 1_788_800_000_000 // P * P + 90_000                # 90 s past a boundary
db = sqlite3.connect(":memory:")
db.execute(collector.SCHEMA_TH)
assert collector.heal(db, now) == 0 and calls == []

def fill(t0, t1, symbols=200):
    db.executemany("INSERT OR REPLACE INTO th_klines VALUES (?,?,0,0,0,0,0,0,0,0)",
                   [(t, f"S{i}") for t in range(t0 // P * P, t1, P) for i in range(symbols)])

fill(now - 8 * 86_400_000, now)                          # whole, older than the window too
assert collector.heal(db, now) == 0 and calls == []
hole = now - 6 * 3_600_000                               # 6 h ago, 30 minutes wide
db.execute("DELETE FROM th_klines WHERE ts >= ? AND ts < ?", (hole, hole + 6 * P))
d = collector.heal(db, now)
assert 0.25 < d < 0.27 and calls == [("th", d), ("fut", d)], (d, calls)
fill(hole, hole + 6 * P)
db.execute("DELETE FROM th_klines WHERE ts >= ?", (now - 12 * 3_600_000,))   # the PC was off
calls.clear()
d = collector.heal(db, now)
assert 0.5 < d < 0.52 and calls == [("th", d), ("fut", d)], (d, calls)
db.execute("DELETE FROM th_klines WHERE symbol IN ('S0','S1','S2')")           # 3 delistings are not a hole
fill(now - 12 * 3_600_000, now, symbols=197)
calls.clear()
assert collector.heal(db, now) == 0 and calls == []
print("ok")
