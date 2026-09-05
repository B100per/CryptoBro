import os, sqlite3, tempfile
import notify, paper

notify.send = lambda *a, **k: False
paper.DB = os.path.join(tempfile.mkdtemp(), "paper.db")

PX = {"AAAUSDT": 10.0, "BBBUSDT": 20.0, "CCCUSDT": 5.0}
paper.prices = lambda: dict(PX)
paper.TOP = 2

def set_scores(d):
    paper.scores = lambda quote="USDT": (d, "th_klines")

c = paper.db()

# first step deploys the whole notional into the top scorers, minus fees
set_scores({"AAAUSDT": 2.0, "BBBUSDT": 1.5, "CCCUSDT": 0.1})
r = paper.step(c, now=1)
assert sorted(r["picks"]) == ["AAAUSDT", "BBBUSDT"]
assert r["equity"] < paper.START_EQUITY          # fees were paid
assert r["equity"] > paper.START_EQUITY * 0.99   # but only fees
assert r["cash"] >= 0          # fully deployed, never overdrawn

# a coin dropping out of the ranking is sold, the new one bought
set_scores({"CCCUSDT": 3.0, "AAAUSDT": 2.0, "BBBUSDT": -1.0})
r = paper.step(c, now=2)
assert sorted(r["picks"]) == ["AAAUSDT", "CCCUSDT"]
held = {s for (s,) in c.execute("SELECT symbol FROM positions")}
assert "BBBUSDT" not in held

# a price move must show up as equity, not vanish
PX["AAAUSDT"] = 20.0
set_scores({"CCCUSDT": 3.0, "AAAUSDT": 2.0})
before = paper.status(c)["equity"]
r = paper.step(c, now=3)
assert r["equity"] > before

# nothing scoring means everything is sold and equity sits in cash
set_scores({"AAAUSDT": -5.0, "CCCUSDT": -5.0})
r = paper.step(c, now=4)
assert r["picks"] == [] and r["holdings"] == 0
assert abs(r["cash"] - r["equity"]) < 1e-9
assert c.execute("SELECT count(*) FROM positions").fetchone()[0] == 0

# cash must never go negative across the whole run
for _, cash_v, _, _ in c.execute("SELECT * FROM equity"):
    assert cash_v >= -1e-9

s = paper.status(c)
assert s["steps"] == 4 and s["fills"] > 0
print("ok")

# --mark values the portfolio without trading: a price move shows up as equity,
# and not one unit changes hands.
before_pos = sorted(c.execute("SELECT symbol, units FROM positions"))
before_fills = c.execute("SELECT count(*) FROM fills").fetchone()[0]
PX["AAAUSDT"] = 40.0
m = paper.mark(c, now=99)
assert sorted(c.execute("SELECT symbol, units FROM positions")) == before_pos
assert c.execute("SELECT count(*) FROM fills").fetchone()[0] == before_fills
assert m["equity"] > paper.status(c)["equity"] * 0.999   # recorded, not discarded
assert c.execute("SELECT equity FROM equity WHERE ts=99").fetchone()[0] == m["equity"]

# ...and a mark with nothing held is just the cash.
c.execute("DELETE FROM positions")
assert abs(paper.mark(c, now=100)["holdings"]) < 1e-12
print("ok")
