"""Keep the database from growing without bound.

5m bars for 384 pairs is ~140k rows a day, about 3 GB a year. Nobody needs
five-minute resolution from eight months ago: it is read once during a
backtest, if ever. So keep 5m for the recent window and roll everything older
into 1h bars, which is 12x smaller and answers the same long-horizon question.

    python3 retention.py            # roll up and delete, default 30 days
    python3 retention.py --days 60
    python3 retention.py --dry-run  # report what would be rolled, change nothing

Safe to run repeatedly: rolled buckets are written before the 5m rows they
came from are deleted, and re-running finds nothing left to do.
"""
import sqlite3
import sys
import time

DB = "data.db"
HOUR_MS = 3_600_000
TABLES = {"klines": "klines_1h", "th_klines": "th_klines_1h"}

SCHEMA = """CREATE TABLE IF NOT EXISTS {name} (
  ts INTEGER, symbol TEXT,
  open REAL, high REAL, low REAL, close REAL, volume REAL,
  quote_vol REAL, trades INTEGER, taker_buy_base REAL,
  PRIMARY KEY (ts, symbol))"""

# open is the first bar's open and close the last bar's close, so both need the
# row at an end of the bucket rather than an aggregate over it.
ROLLUP = """
INSERT OR REPLACE INTO {dst}
SELECT bucket, symbol,
       MIN(CASE WHEN ts = first_ts THEN open END),
       MAX(high), MIN(low),
       MIN(CASE WHEN ts = last_ts THEN close END),
       SUM(volume), SUM(quote_vol), SUM(trades), SUM(taker_buy_base)
FROM (
  SELECT *, ts / {hour} * {hour} AS bucket,
         MIN(ts) OVER w AS first_ts, MAX(ts) OVER w AS last_ts
  FROM {src} WHERE ts < ?
  WINDOW w AS (PARTITION BY symbol, ts / {hour} * {hour})
)
GROUP BY bucket, symbol"""


def rollup(db, src, dst, cutoff, dry_run=False):
    db.execute(SCHEMA.format(name=dst))
    n = db.execute(f"SELECT count(*) FROM {src} WHERE ts < ?", (cutoff,)).fetchone()[0]
    if not n or dry_run:
        return n, 0
    db.execute(ROLLUP.format(dst=dst, src=src, hour=HOUR_MS), (cutoff,))
    written = db.execute(f"SELECT changes()").fetchone()[0]
    db.execute(f"DELETE FROM {src} WHERE ts < ?", (cutoff,))
    db.commit()
    return n, written


def main():
    days = int(sys.argv[sys.argv.index("--days") + 1]) if "--days" in sys.argv else 30
    dry = "--dry-run" in sys.argv
    cutoff = int(time.time() * 1000) - days * 86_400_000

    db = sqlite3.connect(DB, timeout=30)
    before = db.execute("SELECT page_count * page_size FROM pragma_page_count(), "
                        "pragma_page_size()").fetchone()[0]
    for src, dst in TABLES.items():
        if not db.execute("SELECT count(*) FROM sqlite_master WHERE name=?",
                          (src,)).fetchone()[0]:
            continue
        rolled, written = rollup(db, src, dst, cutoff, dry)
        print(f"{src}: {rolled:,} bars older than {days}d"
              + (" (dry run)" if dry else f" -> {written:,} hourly bars"))
    if not dry:
        # VACUUM rewrites the whole file and so needs it to itself. The collector
        # writes every 5 minutes and never stops, so the lock is the normal case,
        # not an error: the rollup above has already freed those pages for reuse
        # inside the file, only the file on disk stays as big as its high-water mark.
        try:
            db.execute("VACUUM")
        except sqlite3.OperationalError as e:
            print(f"vacuum skipped ({e}); pages are free for reuse, file not shrunk")
            return
        after = db.execute("SELECT page_count * page_size FROM pragma_page_count(), "
                           "pragma_page_size()").fetchone()[0]
        print(f"db {before / 1e6:.0f} MB -> {after / 1e6:.0f} MB")


if __name__ == "__main__":
    main()
