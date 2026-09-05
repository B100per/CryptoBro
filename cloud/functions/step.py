"""One paper step, Firebase side: the same rules as paper.py, fed from
binance.th live instead of data.db.

Nothing here imports Firebase, so test_step.py can run it on this machine
with a fake fetch and a dict for a book. main.py is the only file that knows
what Firestore is. Nothing here can place an order: no key is read and the
exchange client is not imported.

Ranking mirrors paper.scores / paper.liquid / paper.breadth exactly, but over
bars held in memory instead of rows in sqlite. The chart rule scores price
only (score(chart, None)), which is what the lab measured; see backtest.py.
"""
import json
import sys
import time
import urllib.parse
import urllib.request

import book
import features
import signals

TH = "https://api.binance.th"
START_EQUITY = 1000.0     # USDT, notional. No real money is involved.
TOP = 5
FEE = 0.001
BARS = 2017               # 7 d of 5 m bars + 1: what vol-scaled momentum needs
PAGE = 1000               # the most binance.th returns per klines call

# Same two books as control.STRATEGIES; `name` is the Firestore document id.
# `stop` is the stop-loss watch() applies between rebalances (lab_stop.out).
STRATEGIES = [
    {"name": "chart", "title": "chart + breadth 60%", "stop": 0.0,
     "rule": "chart", "breadth_floor": 0.6, "min_vol": 2000, "min_score": 0.5},
    {"name": "volmom", "title": "vol-scaled momentum 7d", "stop": 0.15,
     "rule": "volmom", "breadth_floor": 0.0, "min_vol": 2000, "min_score": 0.0},
]
MARKS = 288 * 7           # 5-minute marks kept on the book (`watch`): a week, ~80 KB


def get(path, tries=3, **params):
    url = TH + path + ("?" + urllib.parse.urlencode(params) if params else "")
    for i in range(tries):
        try:
            with urllib.request.urlopen(url, timeout=20) as r:
                return json.load(r)
        except Exception as e:  # ponytail: retry everything, backoff 1/2/4s
            if i == tries - 1:
                raise
            print(f"retry {path} {params}: {e}", file=sys.stderr)
            time.sleep(2 ** i)


def klines(symbol, n=BARS, fetch=get):
    """The newest `n` 5-minute bars as (ts, open, high, low, close, volume),
    oldest first, paged backwards with endTime a page at a time."""
    rows = []
    while len(rows) < n:
        p = {"symbol": symbol, "interval": "5m", "limit": min(PAGE, n - len(rows))}
        if rows:
            p["endTime"] = rows[0][0] - 1
        batch = fetch("/api/v1/klines", **p)
        rows = [(int(k[0]), float(k[1]), float(k[2]), float(k[3]), float(k[4]),
                 float(k[5])) for k in batch] + rows
        if len(batch) < p["limit"]:     # the coin is younger than a week
            break
    return rows


def market(fetch=get, quote="USDT"):
    """Every tradable USDT pair with its last week of bars, and current prices.

    ~384 symbols × 3 pages, one call at a time: latency alone keeps it near
    200 calls a minute, well under the exchange's weight limit, and a step
    that takes eight minutes twice a day costs nothing worth optimising.
    """
    info = fetch("/api/v1/exchangeInfo")
    bars = {}
    for s in info["symbols"]:
        if s.get("status") != "TRADING" or s["quoteAsset"] != quote:
            continue
        try:
            bars[s["symbol"]] = klines(s["symbol"], fetch=fetch)
        except Exception as e:           # one bad coin must not lose the step
            print(f"skip {s['symbol']}: {e}", file=sys.stderr)
    prices = {t["symbol"]: float(t["price"]) for t in fetch("/api/v1/ticker/price")}
    return bars, prices


def liquid(bars, min_vol, n=288):
    """Symbols whose median quote volume per bar over the last day clears min_vol."""
    out = set()
    for sym, rows in bars.items():
        qv = sorted(r[4] * r[5] for r in rows[-n:])
        if qv and qv[len(qv) // 2] >= min_vol:
            out.add(sym)
    return out


def breadth(bars, n=288):
    """Share of the board above where it was a day ago. Stables count, as in paper.py."""
    pairs = [(rows[-n - 1][4], rows[-1][4]) for rows in bars.values() if len(rows) > n]
    tot = sum(1 for then, _ in pairs if then > 0)
    up = sum(1 for then, now in pairs if then > 0 and now > then)
    return up / tot if tot else 1.0


def scores(bars, rule, min_vol=0.0, quote="USDT"):
    keep = liquid(bars, min_vol) if min_vol else None
    volmom = signals.vol_scaled_momentum(BARS - 1)
    out = {}
    for sym, rows in bars.items():
        if book.is_stable_pair(sym, quote) or (keep is not None and sym not in keep):
            continue
        if rule == "chart":
            chart = features.chart_read([r[1:6] for r in rows[-200:]])
            v = features.score(chart, None) if chart else None
        elif rule == "volmom":
            v = volmom(rows, len(rows) - 1)
        else:
            raise ValueError(f"unknown rule {rule!r}")
        if v is not None:
            out[sym] = v
    return out


def summary(curve):
    """What paper.status reports, from the equity curve alone."""
    peak, dd = curve[0]["equity"], 0.0
    for p in curve:
        peak = max(peak, p["equity"])
        dd = max(dd, (peak - p["equity"]) / peak if peak else 0.0)
    last = curve[-1]["equity"]
    return {"steps": len(curve), "started": curve[0]["ts"], "equity": last,
            "return_pct": (last - START_EQUITY) / START_EQUITY * 100,
            "max_drawdown_pct": dd * 100}


def step(state, st, bars, prices, now=None):
    """Advance one book. `state` is the book document (or {} to start at
    1000 USDT); returns the new document and the fills, both plain JSON so
    Firestore, a file, or a test can hold them. Pure apart from the clock."""
    now = now or int(time.time() * 1000)
    state = state or {}
    held = {s: tuple(v) for s, v in state.get("held", {}).items()}
    sc = scores(bars, st["rule"], st["min_vol"])
    picks = book.select(sc, prices, TOP, st["min_score"])
    if st["breadth_floor"] and picks and breadth(bars) < st["breadth_floor"]:
        picks = []
    cash, held, fills = book.rebalance(state.get("cash", START_EQUITY), held, prices,
                                       picks, now, fee=FEE)
    _, holdings, equity = book.value(cash, held, prices)
    curve = state.get("curve", []) + [{"ts": now, "equity": equity}]
    doc = {**summary(curve), "title": st["title"], "cash": cash, "holdings": holdings,
           "held": {s: list(v) for s, v in held.items()}, "curve": curve,
           "marks": {s: prices[s] for s in held},      # so the page can value each coin
           "picks": picks, "scored": len(sc), "updated": now}
    return doc, [dict(zip(("ts", "side", "symbol", "units", "price", "fee"), f))
                 for f in fills]


def watch(state, st, prices, now=None):
    """Between rebalances: value the book at live prices and fire its stop.

    Appends a mark to `watch` (capped at a week) and, when a holding is at or
    under (1 - stop) of its entry, sells it (book.stop_out). Returns the
    fields to merge into the document and the fills. No bars are fetched:
    one price call serves both books.
    """
    now = now or int(time.time() * 1000)
    state = state or {}
    held = {s: tuple(v) for s, v in state.get("held", {}).items()}
    cash, held, fills = book.stop_out(state.get("cash", START_EQUITY), held, prices,
                                      st.get("stop", 0.0), now, fee=FEE)
    _, holdings, equity = book.value(cash, held, prices)
    doc = {"watch": (state.get("watch", []) + [{"ts": now, "equity": equity}])[-MARKS:],
           "marks": {s: prices[s] for s in held if s in prices},   # live prices for the table
           "equity": equity, "holdings": holdings, "marked": now}
    if fills:
        doc.update(cash=cash, held={s: list(v) for s, v in held.items()},
                   watch_note=f"stop-loss sold {', '.join(f[2] for f in fills)}")
    return doc, [dict(zip(("ts", "side", "symbol", "units", "price", "fee"), f))
                 for f in fills]
