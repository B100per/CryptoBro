import os, sqlite3, tempfile
import dashboard

d = tempfile.mkdtemp()
db = os.path.join(d, "paper.db")
c = sqlite3.connect(db)
c.executescript(
    "CREATE TABLE equity(ts INTEGER PRIMARY KEY, cash REAL, holdings REAL, equity REAL);"
    "CREATE TABLE positions(symbol TEXT PRIMARY KEY, units REAL, entry REAL, ts INTEGER);")
c.executemany("INSERT INTO equity VALUES (?,?,?,?)",
              [(1, 0, 1000, 1000.0), (2, 0, 990, 990.0), (3, 0, 1020, 1020.0)])
c.execute("INSERT INTO positions VALUES ('AAAUSDT', 1.5, 2.0, 1)")
c.commit()

# A page that only ever renders green is a page you cannot read.
up = dashboard.render(db, None)
assert "+2.000%" in up and 'class="pct up"' in up, up[:300]
c.execute("UPDATE equity SET equity=900 WHERE ts=3"); c.commit()
down = dashboard.render(db, None)
assert "-10.000%" in down and 'class="pct down"' in down
assert 'class="chart down"' in down, "a losing curve must not be drawn as a winner"

# Missing inputs must degrade, not crash: the lab takes an hour to land.
missing = dashboard.render(os.path.join(d, "no.db"), os.path.join(d, "no.out"))
assert "nothing held" in missing and "still loading" in missing

# A flat curve has zero span; drawing it must not divide by zero.
c.execute("UPDATE equity SET equity=1000"); c.commit()
flat = dashboard.render(db, None)
assert "polyline" in flat and "nan" not in flat.lower()

# One point is not a line yet.
c.execute("DELETE FROM equity WHERE ts>1"); c.commit()
assert "waiting for the second mark" in dashboard.render(db, None)

# Symbol names land in HTML, so they must be escaped rather than trusted.
c.execute("INSERT INTO positions VALUES ('<script>x</script>', 1, 1, 1)")
c.commit()
assert "<script>x" not in dashboard.render(db, None)
# Several lab files render in order, each under its own name; a missing one is skipped.
a, b = os.path.join(d, "a.out"), os.path.join(d, "b.out")
open(a, "w").write("hdr\nrow-from-a\nx")
open(b, "w").write("hdr\nrow-from-b\ny")
multi = dashboard.render(db, f"{a},{os.path.join(d, 'nope.out')},{b}")
assert multi.index("row-from-a") < multi.index("row-from-b")
assert "nope.out" not in multi
print("ok")
