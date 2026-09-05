"""Forward test: the real rule, real prices, imaginary money.

A backtest can only tell you about data the rule was designed against. This
runs the same rule against prices it has never seen, one step at a time, and
keeps the record.

    python3 paper.py --step      # one rebalance, run this on a schedule
    python3 paper.py --step --rule volmom --min-vol 2000 --min-score 0
    python3 paper.py --step --rule chart --breadth 0.6 --min-vol 2000
    python3 paper.py --mark      # record equity at current prices, no trading
    python3 paper.py --status    # portfolio and equity so far
    python3 paper.py --reset     # start a fresh run

State lives in paper.db, deliberately separate from data.db: the collector
holds long write locks during a backfill and this must never wait on it.
"""
import json
import os
import sqlite3
import sys
import time
import urllib.request

import book
import notify
from features import load

# PAPER_DB lets a short experiment run in its own file. Pointing a 1-minute
# observation run at the 12-hourly forward test would overwrite the only
# evidence we have that no backtest can retroactively flatter.
DB = os.environ.get("PAPER_DB", "paper.db")
# Not mode=ro: a read-only connection cannot create the -shm file a WAL
# database needs, so it fails to open while the collector is writing.
DATA_DB = "data.db"
TH = "https://api.binance.th"
START_EQUITY = 1000.0     # USDT, notional. No real money is involved.
TOP = 5
MIN_SCORE = 0.5
FEE = 0.001

SCHEMA = """
CREATE TABLE IF NOT EXISTS positions (symbol TEXT PRIMARY KEY, units REAL, entry REAL, ts INTEGER);
CREATE TABLE IF NOT EXISTS equity (ts INTEGER PRIMARY KEY, cash REAL, holdings REAL, equity REAL);
CREATE TABLE IF NOT EXISTS fills (ts INTEGER, side TEXT, symbol TEXT, units REAL, price REAL, fee REAL);
CREATE TABLE IF NOT EXISTS meta (k TEXT PRIMARY KEY, v TEXT);
"""


def db(path=None):
    c = sqlite3.connect(path or DB)
    c.executescript(SCHEMA)
    return c


def cash(c, value=None):
    if value is None:
        row = c.execute("SELECT v FROM meta WHERE k='cash'").fetchone()
        return float(row[0]) if row else START_EQUITY
    c.execute("INSERT OR REPLACE INTO meta VALUES ('cash', ?)", (str(value),))


def prices():
    with urllib.request.urlopen(TH + "/api/v1/ticker/price", timeout=15) as r:
        return {t["symbol"]: float(t["price"]) for t in json.load(r)}


def _table(d):
    # LIMIT 1, not count(*): counting ten million rows every step to answer
    # "is it empty" is a full table scan for one bit of information.
    return "th_klines" if d.execute(
        "SELECT 1 FROM sqlite_master WHERE name='th_klines'").fetchone() \
        and d.execute("SELECT 1 FROM th_klines LIMIT 1").fetchone() else "klines"


def liquid(d, table, min_vol, bars=288):
    """Symbols whose median quote volume per bar over the last `bars` clears
    min_vol. Same test the backtest applies, so paper trades the same board."""
    if not min_vol:
        return None
    last = d.execute(f"SELECT max(ts) FROM {table}").fetchone()[0] or 0
    by = {}
    for sym, qv in d.execute(f"SELECT symbol, close*volume FROM {table} WHERE ts > ?",
                             (last - bars * 300000,)):
        by.setdefault(sym, []).append(qv)
    return {s for s, v in by.items() if sorted(v)[len(v) // 2] >= min_vol}


def scores(quote="USDT", rule="chart", min_vol=0.0):
    """Ranked pairs from the TH board under one of the rules the lab kept."""
    d = sqlite3.connect(DATA_DB, uri=True, timeout=60)
    table = _table(d)
    keep = liquid(d, table, min_vol)
    out = {}
    if rule == "chart":
        for sym, v in load(d, table=table).items():
            out[sym] = v["score"]
    elif rule == "volmom":
        from signals import vol_scaled_momentum
        fn = vol_scaled_momentum(2016)
        for (sym,) in d.execute(f"SELECT DISTINCT symbol FROM {table}"):
            rows = d.execute(f"SELECT ts, 0, 0, 0, close, volume FROM {table} "
                             "WHERE symbol=? ORDER BY ts DESC LIMIT 2017", (sym,)).fetchall()
            v = fn(rows[::-1], len(rows) - 1)
            if v is not None:
                out[sym] = v
    else:
        raise ValueError(f"unknown rule {rule!r}")
    out = {s: v for s, v in out.items()
           if s.endswith(quote) and not book.is_stable_pair(s, quote)
           and (keep is None or s in keep)}
    return out, table


def breadth(bars=288, quote="USDT"):
    """Share of the board above where it was `bars` ago. Below a floor, the
    step buys nothing: a long-only book's one move in a falling market."""
    d = sqlite3.connect(DATA_DB, uri=True, timeout=60)
    table = _table(d)
    up = tot = 0
    for (sym,) in d.execute(f"SELECT DISTINCT symbol FROM {table} WHERE symbol LIKE ?",
                            (f"%{quote}",)):
        pair = d.execute(f"SELECT close FROM {table} WHERE symbol=? ORDER BY ts DESC "
                         "LIMIT 1 OFFSET ?", (sym, bars)).fetchone()
        now = d.execute(f"SELECT close FROM {table} WHERE symbol=? ORDER BY ts DESC LIMIT 1",
                        (sym,)).fetchone()
        if pair and now and pair[0] > 0:
            tot += 1
            up += now[0] > pair[0]
    return up / tot if tot else 1.0


def mark(c, now=None, stop=0.0):
    """Value the portfolio at current prices, trading nothing unless a stop hits.

    Watching a position for half an hour is worth doing; paying a round trip
    every minute to do it is not. This records the curve and, with `stop`,
    sells only what has fallen through its floor (see book.stop_out): the one
    exit that cannot wait for the next scheduled step.
    """
    now = now or int(time.time() * 1000)
    px = prices()
    held = {s: (u, e) for s, u, e, _ in c.execute("SELECT * FROM positions")}
    bal, held, fills = book.stop_out(cash(c), held, px, stop, now, fee=FEE)
    if fills:
        c.execute("DELETE FROM positions")
        c.executemany("INSERT INTO positions VALUES (?,?,?,?)",
                      [(sym, u, e, now) for sym, (u, e) in held.items()])
        c.executemany("INSERT INTO fills VALUES (?,?,?,?,?,?)", fills)
        cash(c, bal)
    _, holdings, _ = book.value(bal, held, px)
    c.execute("INSERT OR REPLACE INTO equity VALUES (?,?,?,?)",
              (now, bal, holdings, bal + holdings))
    c.commit()
    return {"equity": bal + holdings, "cash": bal, "holdings": holdings,
            "stopped": [f[2] for f in fills]}


def step(c, now=None, rule="chart", breadth_floor=0.0, min_vol=0.0, min_score=None):
    now = now or int(time.time() * 1000)
    min_score = MIN_SCORE if min_score is None else min_score
    px = prices()
    sc, table = scores(rule=rule, min_vol=min_vol)
    held = {s: (u, e) for s, u, e, _ in c.execute("SELECT * FROM positions")}

    picks = book.select(sc, px, TOP, min_score)
    if breadth_floor and picks and breadth() < breadth_floor:
        picks = []

    bal, after, fills = book.rebalance(cash(c), held, px, picks, now, fee=FEE)
    c.execute("DELETE FROM positions")
    c.executemany("INSERT INTO positions VALUES (?,?,?,?)",
                  [(sym, u, e, now) for sym, (u, e) in after.items()])
    c.executemany("INSERT INTO fills VALUES (?,?,?,?,?,?)", fills)
    cash(c, bal)
    _, holdings, _ = book.value(bal, after, px)
    c.execute("INSERT OR REPLACE INTO equity VALUES (?,?,?,?)",
              (now, bal, holdings, bal + holdings))
    c.commit()
    return {"equity": bal + holdings, "cash": bal, "holdings": holdings,
            "picks": picks, "scored": len(sc), "table": table}


def status(c):
    rows = c.execute("SELECT ts, equity FROM equity ORDER BY ts").fetchall()
    pos = c.execute("SELECT symbol, units, entry FROM positions").fetchall()
    fills = c.execute("SELECT count(*) FROM fills").fetchone()[0]
    if not rows:
        return {"steps": 0}
    first, last = rows[0][1], rows[-1][1]
    peak, dd = first, 0.0
    for _, e in rows:
        peak = max(peak, e)
        dd = max(dd, (peak - e) / peak if peak else 0)
    return {"steps": len(rows), "started": rows[0][0], "equity": last,
            "return_pct": (last - START_EQUITY) / START_EQUITY * 100,
            "max_drawdown_pct": dd * 100, "fills": fills, "positions": pos}


def main():
    c = db()
    if "--reset" in sys.argv:
        for t in ("positions", "equity", "fills", "meta"):
            c.execute(f"DELETE FROM {t}")
        c.commit()
        print("reset")
        return
    if "--status" in sys.argv:
        s = status(c)
        print(json.dumps({k: v for k, v in s.items() if k != "positions"}, indent=2))
        for sym, units, entry in s.get("positions", []):
            print(f"  {sym:<14} {units:>16.8f} @ {entry}")
        return

    if "--mark" in sys.argv:
        r = mark(c)
        s = status(c)
        print(f"{time.strftime('%H:%M:%S')} equity={r['equity']:.4f} "
              f"cash={r['cash']:.2f} holdings={r['holdings']:.4f} "
              f"({s['return_pct']:+.3f}%)")
        return

    arg = lambda n, d, cast=float: cast(sys.argv[sys.argv.index(n) + 1]) if n in sys.argv else d
    r = step(c, rule=arg("--rule", "chart", str), breadth_floor=arg("--breadth", 0.0),
             min_vol=arg("--min-vol", 0.0), min_score=arg("--min-score", None))
    print(f"equity={r['equity']:.2f} cash={r['cash']:.2f} holdings={r['holdings']:.2f} "
          f"scored={r['scored']} ({r['table']}) picks={','.join(r['picks']) or '-'}")
    if "--notify" in sys.argv:
        s = status(c)
        notify.send("Paper trading",
                    f"equity {r['equity']:.2f} USDT ({s['return_pct']:+.2f}%)\n"
                    f"holding: {', '.join(r['picks']) or 'nothing'}\n"
                    f"max drawdown {s['max_drawdown_pct']:.2f}% over {s['steps']} steps",
                    "good" if s["return_pct"] >= 0 else "warn")


if __name__ == "__main__":
    main()
