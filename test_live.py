import sqlite3

import live
import notify
import paper
from binance_th import BinanceTH

notify.send = lambda *a, **k: False
live.journal.record = lambda *a, **k: None
PX = {"AAAUSDT": 10.0, "BBBUSDT": 20.0, "CCCUSDT": 5.0, "DDDUSDT": 2.0, "EEEUSDT": 1.0,
      "FFFUSDT": 4.0, "USDCUSDT": 1.0}
SCORES = {"AAAUSDT": 3.0, "BBBUSDT": 2.5, "CCCUSDT": 2.0, "DDDUSDT": 1.5, "EEEUSDT": 1.0,
          "FFFUSDT": 0.5}                 # paper.scores has already dropped the stables
paper.scores = lambda **k: (SCORES, "th_klines")
sent = []


def stub(cap, balances):
    c = BinanceTH(key="k", secret="s", max_notional=cap)
    c._filters = {p: {"LOT_SIZE": {"stepSize": "0.001"}, "NOTIONAL": {"minNotional": "10"}}
                  for p in PX}
    c.balances = lambda: dict(bal)
    bal = dict(balances)

    def order(pair, side, qty, quote="USDT"):     # fills at 0.1 % worse than planned
        qty = c.round_qty(pair, qty)
        price = PX[pair] * (1.001 if side == "BUY" else 0.999)
        asset = pair[:-4]
        if side == "BUY":
            bal["USDT"] -= qty * price
            bal[asset] = bal.get(asset, 0.0) + qty
        else:
            bal["USDT"] = bal.get("USDT", 0.0) + qty * price
            bal[asset] -= qty
        sent.append((side, pair, qty))
        return {"executedQty": str(qty), "cummulativeQuoteQty": str(qty * price), "orderId": 1}
    c.order = order
    return c


db = sqlite3.connect(":memory:")
db.executescript(paper.SCHEMA)

# an empty account: five equal buys, the sixth left out, nothing over the cap
c = stub(1000, {"USDT": 1000.0})
picks, h, fills = live.plan(c, db, PX, now=1)
assert picks == ["AAAUSDT", "BBBUSDT", "CCCUSDT", "DDDUSDT", "EEEUSDT"] and h == {}
assert [f[1] for f in fills] == ["BUY"] * 5 and abs(sum(f[3] * f[4] for f in fills) - 999) < 1

# the cap, not the balance, sizes the book
_, _, capped = live.plan(stub(300, {"USDT": 1000.0}), db, PX, now=1)
assert abs(sum(f[3] * f[4] for f in capped) - 300) < 1

# a dry run sends nothing and records nothing
live.execute(c, db, fills, h, now=1, live=False)
assert sent == [] and db.execute("SELECT count(*) FROM positions").fetchone()[0] == 0

# live: every order goes out, and the entries are the prices actually filled
live.execute(c, db, fills, h, now=1, live=True)
assert [s[0] for s in sent] == ["BUY"] * 5
entries = dict(db.execute("SELECT symbol, entry FROM positions"))
assert abs(entries["AAAUSDT"] - 10.01) < 1e-9, entries
cash, holdings, equity = live.mark(c, db, PX, now=2)
assert cash < 2 and 990 < equity < 1000, (cash, equity)

# the watch: a coin 20 % under its entry is sold, one 10 % under is kept, no prompt needed
crash = {**PX, "AAAUSDT": 8.0, "BBBUSDT": 18.0}
_, h, stops = live.plan(c, db, crash, now=3, watch=True)
assert [(f[1], f[2]) for f in stops] == [("STOP", "AAAUSDT")]
live.execute(c, db, stops, h, now=3, live=True)
assert sent[-1][:2] == ("SELL", "AAAUSDT") and "AAAUSDT" not in c.balances() or c.balances()["AAAUSDT"] < 0.001
assert "AAAUSDT" not in dict(db.execute("SELECT symbol, entry FROM positions"))
assert db.execute("SELECT side FROM fills ORDER BY rowid DESC LIMIT 1").fetchone()[0] == "STOP"

# a coin found in the account with no entry is adopted at today's price
c2 = stub(1000, {"USDT": 100.0, "FFF": 5.0, "EEE": 0.5})   # EEE is 0.5 USDT of dust
h = live.held(c2, db, PX)
assert h == {"FFFUSDT": (5.0, 4.0)}, h

# what the exchange would refuse is shown as a skip, not sent
assert live.refusal(c, "AAAUSDT", 0.5, 10.0) == "under the 10 USDT minimum"
assert live.refusal(c, "AAAUSDT", 0.0001, 10.0) == "rounds to zero at this step size"
assert live.refusal(c, "AAAUSDT", 2.0, 10.0) is None
print("ok")
