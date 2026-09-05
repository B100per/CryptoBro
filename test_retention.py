import sqlite3, time
from retention import rollup, HOUR_MS, SCHEMA

db = sqlite3.connect(":memory:")
db.execute(SCHEMA.format(name="klines"))

# two full hours of 5m bars for one symbol, plus one recent bar that must survive
base = 1_700_000_000_000 // HOUR_MS * HOUR_MS
rows = []
for h in range(2):
    for i in range(12):
        ts = base + h * HOUR_MS + i * 300_000
        price = 100 + h * 10 + i
        rows.append((ts, "BTCUSDT", price, price + 5, price - 5, price + 1,
                     2.0, 200.0, 10, 1.0))
recent = (base + 5 * HOUR_MS, "BTCUSDT", 999, 999, 999, 999, 1.0, 1.0, 1, 1.0)
rows.append(recent)
db.executemany("INSERT INTO klines VALUES (" + ",".join("?" * 10) + ")", rows)

cutoff = base + 2 * HOUR_MS
seen, written = rollup(db, "klines", "klines_1h", cutoff)
assert seen == 24 and written == 2, (seen, written)

out = db.execute("SELECT ts, open, high, low, close, volume, trades "
                 "FROM klines_1h ORDER BY ts").fetchall()
assert len(out) == 2
ts0, o, h, l, c, v, t = out[0]
assert ts0 == base
assert o == 100                 # first bar's open, not the min or the mean
assert c == 100 + 11 + 1        # last bar's close
assert h == 100 + 11 + 5        # highest high in the hour
assert l == 100 - 5             # lowest low
assert v == 24.0 and t == 120   # volume and trade count summed
assert out[1][1] == 110         # second hour opens where its own first bar did

# the recent bar is untouched, the rolled ones are gone
left = db.execute("SELECT ts FROM klines").fetchall()
assert left == [(recent[0],)]

# running again finds nothing to do and changes nothing
seen, written = rollup(db, "klines", "klines_1h", cutoff)
assert seen == 0 and written == 0
assert db.execute("SELECT count(*) FROM klines_1h").fetchone()[0] == 2

# dry run must never delete
db.executemany("INSERT INTO klines VALUES (" + ",".join("?" * 10) + ")", rows[:12])
seen, written = rollup(db, "klines", "klines_1h", cutoff, dry_run=True)
assert seen == 12 and written == 0
assert db.execute("SELECT count(*) FROM klines WHERE ts < ?", (cutoff,)).fetchone()[0] == 12
print("ok")
