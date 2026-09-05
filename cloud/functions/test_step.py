"""python3 cloud/functions/test_step.py — no network, no Firebase."""
import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", ".."))
import step  # noqa: E402

N = step.BARS + 50


def bars(start, slope, vol=100.0, n=N, rng=None):
    """A coin drifting `slope` per bar. Its range shrinks over time, so the
    regime gate sees calm, not "volatile"; rng=const keeps it flat instead."""
    out = []
    for j in range(n):
        c = start + slope * j
        r = rng if rng is not None else max(0.2, 3.0 - j / n * 2.8)
        out.append((j * 300000, c, c + r, c - r, c, vol))
    return out


BOARD = {
    "UPUSDT": bars(100.0, 0.05),                 # rising, liquid
    "DOWNUSDT": bars(400.0, -0.05),              # falling
    "THINUSDT": bars(100.0, 0.06, vol=0.001),    # rising harder, but nobody trades it
    "USDCUSDT": bars(1.0, 0.0, vol=1e6, rng=0.001),  # a stable: never bought
    "FLATUSDT": bars(50.0, 0.0),
}
PX = {s: rows[-1][4] for s, rows in BOARD.items()}
PX["ORPHANUSDT"] = 1.0                           # priced but no bars: not pickable

# ── paging: 2017 bars come back oldest-first from three endTime pages ────
def fetch(path, **p):
    if path == "/api/v1/exchangeInfo":
        return {"symbols": [{"symbol": s, "status": "TRADING", "quoteAsset": "USDT"} for s in BOARD]
                + [{"symbol": "OLDUSDT", "status": "BREAK", "quoteAsset": "USDT"},
                   {"symbol": "UPTHB", "status": "TRADING", "quoteAsset": "THB"}]}
    if path == "/api/v1/ticker/price":
        return [{"symbol": s, "price": str(v)} for s, v in PX.items()]
    rows = BOARD[p["symbol"]]
    end = p.get("endTime", rows[-1][0])
    page = [r for r in rows if r[0] <= end][-p["limit"]:]
    fetch.calls.append((p["symbol"], p["limit"], p.get("endTime")))
    return [[r[0], str(r[1]), str(r[2]), str(r[3]), str(r[4]), str(r[5])] for r in page]
fetch.calls = []

k = step.klines("UPUSDT", fetch=fetch)
assert len(k) == step.BARS and k[0][0] < k[-1][0] and k[-1] == BOARD["UPUSDT"][-1]
assert [c[1] for c in fetch.calls] == [1000, 1000, 17], fetch.calls
assert [c[0] for c in fetch.calls] == ["UPUSDT"] * 3 and len({r[0] for r in k}) == step.BARS
assert len(step.klines("UPUSDT", n=20, fetch=fetch)) == 20

mkt, px = step.market(fetch=fetch)
assert set(mkt) == set(BOARD), "only TRADING USDT pairs"
assert px["UPUSDT"] == PX["UPUSDT"] and "ORPHANUSDT" in px

# ── ranking mirrors paper.py ───────────────────────────────────────────
assert step.liquid(mkt, 2000) == {"UPUSDT", "DOWNUSDT", "USDCUSDT", "FLATUSDT"}
vm = step.scores(mkt, "volmom", min_vol=2000)
assert "USDCUSDT" not in vm and "THINUSDT" not in vm, "stables and thin coins never rank"
assert vm["UPUSDT"] > 0 > vm["DOWNUSDT"]
assert "THINUSDT" in step.scores(mkt, "volmom", min_vol=0), "no floor, no filter"
ch = step.scores(mkt, "chart", min_vol=2000)
assert ch["UPUSDT"] > 0.5 > ch["DOWNUSDT"], ch
assert step.breadth(mkt) == 2 / 5, "two of five above yesterday's close"

# ── a book stepping through time ───────────────────────────────────────
volmom, chart = step.STRATEGIES[1], step.STRATEGIES[0]
doc, fills = step.step(None, volmom, mkt, px, now=1)
assert doc["picks"] == ["UPUSDT"] and set(doc["held"]) == {"UPUSDT"}
assert doc["marks"] == {"UPUSDT": px["UPUSDT"]}, "the page values coins from marks"
assert 990 < doc["equity"] < 1000 and doc["cash"] >= 0 and doc["steps"] == 1
assert [f["side"] for f in fills] == ["BUY"] and fills[0]["symbol"] == "UPUSDT"

# the breadth gate: same board, chart book buys nothing while 4 of 5 are down
gated, fills = step.step(None, chart, mkt, px, now=1)
assert gated["picks"] == [] and gated["held"] == {} and fills == []
assert gated["equity"] == step.START_EQUITY

# a price move shows up as equity, and a coin that stops ranking is sold
px2 = {**px, "UPUSDT": px["UPUSDT"] * 1.5}
doc2, _ = step.step(doc, volmom, mkt, px2, now=2)
assert doc2["equity"] > doc["equity"] and doc2["return_pct"] > 40 and doc2["steps"] == 2
falling = {**mkt, "UPUSDT": bars(300.0, -0.05)}
doc3, fills = step.step(doc2, volmom, falling, px2, now=3)
assert doc3["held"] == {} and [f["side"] for f in fills] == ["SELL"] and doc3["cash"] > 0
assert doc3["max_drawdown_pct"] >= 0 and [p["ts"] for p in doc3["curve"]] == [1, 2, 3]

# ── watch: a mark between rebalances, and the stop-loss on the volmom book ──
w, fills = step.watch(doc, volmom, px, now=5)
assert fills == [] and w["watch"] == [{"ts": 5, "equity": doc["equity"]}] and "held" not in w
assert w["marks"] == {"UPUSDT": px["UPUSDT"]}, "the table still gets live prices"
crash = {**px, "UPUSDT": px["UPUSDT"] * 0.8}                 # -20% > the 15% stop
w2, fills = step.watch({**doc, **w}, volmom, crash, now=6)
assert [f["side"] for f in fills] == ["STOP"] and w2["held"] == {} and w2["cash"] > 0
assert [m["ts"] for m in w2["watch"]] == [5, 6] and "stop-loss sold UPUSDT" in w2["watch_note"]
chart_doc = {**doc, "held": doc["held"]}                     # same holding, no stop on this book
w3, fills = step.watch(chart_doc, chart, crash, now=6)
assert fills == [] and "held" not in w3, "the chart book carries no stop"
long = {**doc, "watch": [{"ts": i, "equity": 1.0} for i in range(step.MARKS)]}
assert len(step.watch(long, volmom, px, now=9)[0]["watch"]) == step.MARKS, "capped at a week"

# what goes to Firestore must survive JSON and must not nest arrays in arrays
json.dumps(doc3)
assert not any(isinstance(x, list) for v in doc3.values() if isinstance(v, list) for x in v)

# nothing in this import graph can reach the exchange with an order
assert "binance_th" not in sys.modules and "binance_client" not in sys.modules
assert "firebase_functions" not in sys.modules
print("ok")
