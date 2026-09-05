"""Forward test: the real rule, real prices, imaginary money.

A backtest can only tell you about data the rule was designed against. This
runs the same rule against prices it has never seen, one step at a time, and
keeps the record.

    python3 paper.py --step      # one rebalance, run this on a schedule
    python3 paper.py --status    # portfolio and equity so far
    python3 paper.py --reset     # start a fresh run

State lives in paper.db, deliberately separate from data.db: the collector
holds long write locks during a backfill and this must never wait on it.
"""
import json
import sqlite3
import sys
import time
import urllib.request

import notify
from features import load

DB = "paper.db"
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


def db():
    c = sqlite3.connect(DB)
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


def scores(quote="USDT"):
    """Ranked pairs from the TH board, using whichever kline table has data."""
    d = sqlite3.connect(DATA_DB, uri=True, timeout=60)
    # LIMIT 1, not count(*): counting ten million rows every step to answer
    # "is it empty" is a full table scan for one bit of information.
    table = "th_klines" if d.execute(
        "SELECT 1 FROM sqlite_master WHERE name='th_klines'").fetchone() \
        and d.execute("SELECT 1 FROM th_klines LIMIT 1").fetchone() else "klines"
    out = {}
    for sym, v in load(d, table=table).items():
        if sym.endswith(quote):
            out[sym] = v["score"]
    return out, table


def step(c, now=None):
    now = now or int(time.time() * 1000)
    px = prices()
    sc, table = scores()
    held = {s: (u, e) for s, u, e, _ in c.execute("SELECT * FROM positions")}

    holdings = sum(u * px[s] for s, (u, _) in held.items() if s in px)
    equity = cash(c) + holdings
    picks = [s for s, v in sorted(sc.items(), key=lambda kv: -kv[1])
             if v >= MIN_SCORE and s in px][:TOP]
    target = equity / len(picks) if picks else 0.0

    bal = cash(c)
    for sym, (units, _) in held.items():
        if sym in picks or sym not in px:
            continue
        proceeds = units * px[sym]
        bal += proceeds * (1 - FEE)
        c.execute("DELETE FROM positions WHERE symbol=?", (sym,))
        c.execute("INSERT INTO fills VALUES (?,?,?,?,?,?)",
                  (now, "SELL", sym, units, px[sym], proceeds * FEE))

    for sym in picks:
        have = held.get(sym, (0.0, 0.0))[0] * px[sym]
        delta = target - have
        if abs(delta) < equity * 0.02:      # not worth the fee to nudge
            continue
        if delta > 0:
            delta = min(delta, max(0.0, bal / (1 + FEE)))
            if delta <= 0:
                continue
        bal -= delta + abs(delta) * FEE
        units = held.get(sym, (0.0, 0.0))[0] + delta / px[sym]
        c.execute("INSERT OR REPLACE INTO positions VALUES (?,?,?,?)",
                  (sym, units, px[sym], now))
        c.execute("INSERT INTO fills VALUES (?,?,?,?,?,?)",
                  (now, "BUY" if delta > 0 else "SELL", sym, abs(delta) / px[sym],
                   px[sym], abs(delta) * FEE))

    # Float noise leaves cash at -5e-14 after spending it all. Round it away so
    # the stored balance is honest, but keep it signed so a real overdraft still shows.
    bal = round(bal, 8)
    cash(c, bal)
    holdings = sum(u * px[s] for s, u, _, _ in c.execute("SELECT * FROM positions") if s in px)
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

    r = step(c)
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
