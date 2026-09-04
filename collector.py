"""Binance USDT-M futures positioning collector.

Polls funding, open interest, top-trader / global long-short ratios and
taker buy/sell volume for the top-N perpetuals every 5 minutes, into sqlite.

    python3 collector.py            # run forever
    python3 collector.py --once     # one cycle then exit
    python3 collector.py --backfill # one cycle, pulling 1000 candles of price history
"""
import json
import sqlite3
import sys
import time
import urllib.parse
import urllib.request

BASE = "https://fapi.binance.com"
DB = "data.db"
TOP_N = 50          # symbols per cycle; 5 data calls each, limit is 1000 req / 5 min per IP
PERIOD_MS = 300_000  # 5m, matches Binance data-endpoint granularity

SCHEMA_KLINES = """CREATE TABLE IF NOT EXISTS klines (
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


def get(path, tries=3, **params):
    url = BASE + path + ("?" + urllib.parse.urlencode(params) if params else "")
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


def save_klines(db, sym, limit):
    """Store 5m candles. Unlike the positioning endpoints, klines have full history,
    so this can backfill years in one call."""
    rows = [(int(k[0]), sym, float(k[1]), float(k[2]), float(k[3]), float(k[4]),
             float(k[5]), float(k[7]), int(k[8]), float(k[9]))
            for k in get("/fapi/v1/klines", symbol=sym, interval="5m", limit=limit)]
    db.executemany("INSERT OR REPLACE INTO klines VALUES (" + ",".join("?" * 10) + ")", rows)
    return len(rows)


def collect_once(db, kline_limit=3):
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
            save_klines(db, sym, kline_limit)
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
    if "--backfill" in sys.argv:
        return collect_once(db, kline_limit=1000)
    if "--once" in sys.argv:
        return collect_once(db)
    while True:
        try:
            collect_once(db)
        except Exception as e:
            print(f"cycle failed: {e}", file=sys.stderr)
        # ponytail: wake 30s after each 5m boundary; Binance publishes data on the boundary
        time.sleep(PERIOD_MS / 1000 - time.time() % (PERIOD_MS / 1000) + 30)


if __name__ == "__main__":
    main()
