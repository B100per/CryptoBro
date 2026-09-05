"""Binance USDT-M futures positioning collector.

Polls funding, open interest, top-trader / global long-short ratios and
taker buy/sell volume for the top-N perpetuals every 5 minutes, into sqlite.

    python3 collector.py            # run forever
    python3 collector.py --once     # one cycle then exit
    python3 collector.py --backfill # one cycle, pulling 1000 candles of price history
    python3 collector.py --history 90  # one cycle, paging back 90 days of candles
"""
import json
import sqlite3
import sys
import time
import urllib.parse
import urllib.request

BASE = "https://fapi.binance.com"
TH_BASE = "https://api.binance.th"
DB = "data.db"
TOP_N = 50          # symbols per cycle; 5 data calls each, limit is 1000 req / 5 min per IP
PERIOD_MS = 300_000  # 5m, matches Binance data-endpoint granularity

SCHEMA_KLINES = """CREATE TABLE IF NOT EXISTS klines (
  ts INTEGER, symbol TEXT,
  open REAL, high REAL, low REAL, close REAL, volume REAL,
  quote_vol REAL, trades INTEGER, taker_buy_base REAL,
  PRIMARY KEY (ts, symbol))"""

SCHEMA_TH = """CREATE TABLE IF NOT EXISTS th_klines (
  ts INTEGER, symbol TEXT,
  open REAL, high REAL, low REAL, close REAL, volume REAL,
  quote_vol REAL, trades INTEGER, taker_buy_base REAL,
  PRIMARY KEY (ts, symbol))"""

SCHEMA = """CREATE TABLE IF NOT EXISTS positioning (
  ts INTEGER, symbol TEXT,
  mark_price REAL, funding REAL, quote_vol_24h REAL,
  oi REAL, oi_value REAL,
  top_acct REAL, top_pos REAL, global_acct REAL,
  taker_ratio REAL, taker_buy REAL, taker_sell REAL,
  PRIMARY KEY (ts, symbol))"""


def get(path, tries=3, base=None, **params):
    url = (base or BASE) + path + ("?" + urllib.parse.urlencode(params) if params else "")
    for i in range(tries):
        try:
            with urllib.request.urlopen(url, timeout=10) as r:
                return json.load(r)
        except Exception as e:  # ponytail: retry everything, backoff 1/2/4s
            if i == tries - 1:
                raise
            print(f"retry {path} {params}: {e}", file=sys.stderr)
            time.sleep(2 ** i)


def top_symbols(tickers, n=TOP_N):
    perps = [t for t in tickers if t["symbol"].endswith("USDT") and "_" not in t["symbol"]]
    perps.sort(key=lambda t: float(t["quoteVolume"]), reverse=True)
    return [t["symbol"] for t in perps[:n]]


def build_row(ts, sym, prem, tick, oi, top_acct, top_pos, glob, taker):
    return (
        ts, sym,
        float(prem["markPrice"]), float(prem["lastFundingRate"]), float(tick["quoteVolume"]),
        float(oi["sumOpenInterest"]), float(oi["sumOpenInterestValue"]),
        float(top_acct["longShortRatio"]), float(top_pos["longShortRatio"]), float(glob["longShortRatio"]),
        float(taker["buySellRatio"]), float(taker["buyVol"]), float(taker["sellVol"]),
    )


def save_klines(db, sym, limit=3, days=None, base=None, path="/fapi/v1/klines",
                table="klines"):
    """Store 5m candles. Unlike the positioning endpoints, klines have full
    history, so `days` pages backwards as far as you ask."""
    def store(batch):
        rows = [(int(k[0]), sym, float(k[1]), float(k[2]), float(k[3]), float(k[4]),
                 float(k[5]), float(k[7]), int(k[8]), float(k[9])) for k in batch]
        db.executemany(f"INSERT OR REPLACE INTO {table} VALUES ("
                       + ",".join("?" * 10) + ")", rows)
        return len(rows)

    if not days:
        return store(get(path, base=base, symbol=sym, interval="5m", limit=limit))

    start = int(time.time() * 1000) - days * 86_400_000
    total, cursor = 0, start
    while cursor < time.time() * 1000:
        batch = get(path, base=base, symbol=sym, interval="5m",
                    startTime=cursor, limit=1000)
        if not batch:
            break
        total += store(batch)
        cursor = int(batch[-1][0]) + PERIOD_MS
        if len(batch) < 1000:
            break
        time.sleep(0.15)   # 1000-bar pages cost weight 5; do not sprint
    return total


def th_symbols(quote="USDT"):
    """Every pair actually tradable on the Thai spot exchange."""
    info = get("/api/v1/exchangeInfo", base=TH_BASE)
    return [s["symbol"] for s in info["symbols"]
            if s.get("status") == "TRADING" and s["quoteAsset"] == quote]


def collect_th(db, limit=3, days=None):
    """5m candles for the whole Binance TH board.

    Spot is long-only, so the only way to make money there is to hold something
    going up. Scoring 21 coins because that is what the futures collector
    happens to cover leaves 363 unexamined for no reason: these klines are
    public and need no key.
    """
    symbols = th_symbols()
    total = 0
    for n, sym in enumerate(symbols, 1):
        try:
            total += save_klines(db, sym, limit, days=days,
                                 base=TH_BASE, path="/api/v1/klines", table="th_klines")
        except Exception as e:
            print(f"skip th {sym}: {e}", file=sys.stderr)
        # Commit per symbol. One transaction across all 384 held a write lock for
        # an hour: nothing else could read the database, and a crash would have
        # rolled the whole backfill back to nothing.
        db.commit()
        if days:
            print(f"th backfill {n}/{len(symbols)} {sym} rows={total}", flush=True)
        time.sleep(0.05)
    return total


def collect_once(db, kline_limit=3, history_days=None):
    ts = int(time.time() * 1000) // PERIOD_MS * PERIOD_MS
    prem = {p["symbol"]: p for p in get("/fapi/v1/premiumIndex")}
    tickers = get("/fapi/v1/ticker/24hr")
    tick = {t["symbol"]: t for t in tickers}
    rows = []
    for sym in top_symbols(tickers):
        try:
            d = lambda ep: get(f"/futures/data/{ep}", symbol=sym, period="5m", limit=1)[0]
            rows.append(build_row(ts, sym, prem[sym], tick[sym],
                                  d("openInterestHist"), d("topLongShortAccountRatio"),
                                  d("topLongShortPositionRatio"), d("globalLongShortAccountRatio"),
                                  d("takerlongshortRatio")))
            save_klines(db, sym, kline_limit, days=history_days)
        except Exception as e:
            print(f"skip {sym}: {e}", file=sys.stderr)
        time.sleep(0.1)
    db.executemany("INSERT OR REPLACE INTO positioning VALUES (" + ",".join("?" * 13) + ")", rows)
    db.commit()
    print(f"{time.strftime('%F %T')} ts={ts} rows={len(rows)}")
    return len(rows)


def main():
    db = sqlite3.connect(DB)
    db.execute(SCHEMA)
    db.execute(SCHEMA_KLINES)
    db.execute(SCHEMA_TH)
    if "--history" in sys.argv:
        days = int(sys.argv[sys.argv.index("--history") + 1])
        collect_th(db, days=days)
        return collect_once(db, history_days=days)
    if "--backfill" in sys.argv:
        return collect_once(db, kline_limit=1000)
    if "--once" in sys.argv:
        collect_th(db)
        return collect_once(db)
    while True:
        try:
            collect_once(db)
            collect_th(db)
        except Exception as e:
            print(f"cycle failed: {e}", file=sys.stderr)
        # ponytail: wake 30s after each 5m boundary; Binance publishes data on the boundary
        time.sleep(PERIOD_MS / 1000 - time.time() % (PERIOD_MS / 1000) + 30)


if __name__ == "__main__":
    main()
