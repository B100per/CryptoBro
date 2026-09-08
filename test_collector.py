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

# heal: a fresh database or a bar 10 minutes old needs nothing; a bar 12 h old
# refills a hair over half a day, through both collectors
calls = []
collector.collect_th = lambda db, days=None: calls.append(("th", days))
collector.collect_once = lambda db, history_days=None: calls.append(("fut", history_days))
db = sqlite3.connect(":memory:")
db.execute(collector.SCHEMA_TH)
now = 1_788_800_000_000
assert collector.heal(db, now) == 0 and calls == []
db.execute("INSERT INTO th_klines VALUES (?,?,0,0,0,0,0,0,0,0)", (now - 2 * collector.PERIOD_MS, "BTCUSDT"))
assert collector.heal(db, now) == 0 and calls == []
db.execute("INSERT INTO th_klines VALUES (?,?,0,0,0,0,0,0,0,0)", (now - 43_200_000, "ETHUSDT"))
db.execute("DELETE FROM th_klines WHERE symbol='BTCUSDT'")
d = collector.heal(db, now)
assert 0.5 < d < 0.52 and calls == [("th", d), ("fut", d)], (d, calls)
print("ok")
