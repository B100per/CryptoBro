"""Is the live chart rule better than the one the backtest measures?

    python3 lab_pos.py > lab_pos.out

backtest.chart_signal scores `score(chart, None)`. features.load, which is
what paper.py and the panel actually run, scores `score(chart, pos)`: funding,
open-interest change and the smart-money/retail split, for the ~148 symbols the
futures collector covers. They are not the same rule, and the difference has
never been measured: on 2026-09-28 the live chart book was +30.9% while every
backtest of it, on 90 and on 108 days, said its BEST start time still lost to
buy-and-hold.

Positioning only exists from 2026-09-05, so this is a 23-day window with real
holes in it (the PC was off for stretches). Both arms run on exactly the same
bars and the same window, so the comparison is fair even though it is short.
Treat the absolute numbers as noise and read only the difference between rows.
"""
import sqlite3
import statistics
import sys

from backtest import WINDOW, chart_signal, load_bars, robust
from features import chart_read, score

DB = "data.db"
PAD = WINDOW + 10            # bars of chart history needed before the first step


def positioning(db):
    """{symbol: [(ts, funding, oi, top_pos, global_acct)]}, oldest first."""
    out = {}
    for sym, ts, f, oi, tp, ga in db.execute(
            "SELECT symbol, ts, funding, oi, top_pos, global_acct FROM positioning ORDER BY ts"):
        out.setdefault(sym, []).append((ts, f, oi, tp, ga))
    return out


def live_signal(pos_by_sym):
    """features.load's score, bar by bar: the rule that is actually running.

    Mirrors features.load exactly, holes included - it takes the last 12 rows
    by row order, not by clock, so a gap makes oi_change span more than an hour.
    Measuring the idealised version would measure a rule nobody runs.
    """
    def fn(rows, i, window=WINDOW, sym=None):
        chart = chart_read([(r[1], r[2], r[3], r[4], r[5]) for r in rows[i - window:i + 1]])
        if not chart:
            return None
        hist = [r for r in pos_by_sym.get(sym, ()) if r[0] <= rows[i][0]][-12:]
        pos = None
        if hist:
            _, f, oi, tp, ga = hist[-1]
            oldest_oi = hist[0][2]
            pos = {"funding": f, "top_pos": tp, "global_acct": ga,
                   "oi_change": (oi / oldest_oi - 1) * 100 if oldest_oi else 0.0}
        return score(chart, pos)
    fn.wants_symbol = True
    return fn


def main():
    db = sqlite3.connect(DB)
    start = db.execute("SELECT min(ts) FROM positioning").fetchone()[0]
    bars = load_bars(db, None, "th_klines")
    span = start - PAD * 300_000
    bars = {s: [r for r in rows if r[0] >= span] for s, rows in bars.items()}
    bars = {s: rows for s, rows in bars.items() if len(rows) > PAD}
    pos = positioning(db)
    covered = sum(1 for s in bars if s in pos)
    print(f"symbols={len(bars)} ({covered} with positioning) "
          f"bars={sum(len(v) for v in bars.values()):,} from the positioning window "
          f"({(max(max(r[0] for r in v) for v in bars.values()) - start) / 86_400_000:.1f} d), "
          f"rebalance=432 (36h), 5 start times", flush=True)
    # Raw return AND excess. Printing excess alone is what made the live book
    # look impossible: +30.9% raw read against a -17.6% excess and called a
    # contradiction. Over a 23-day bull run buy-and-hold is most of the number,
    # so both columns belong on the page.
    print(f"\n{'rule':>28}{'raw%':>8}{'hold%':>8}{'worst_ex%':>11}"
          f"{'median_ex%':>12}{'best_ex%':>10}{'maxDD%':>8}{'trades':>8}")
    for name, fn in (("chart, no positioning", chart_signal),
                     ("chart + positioning (live)", live_signal(pos))):
        for floor, breadth in ((0.5, 0.6),):
            rows = robust(bars, offsets=5, top=5, rebalance=432, fee=0.001, min_score=floor,
                          score_fn=fn, window=WINDOW, min_quote_vol=2000, min_breadth=breadth)
            ex = sorted(m["return_pct"] - h for _, m, h in rows)
            raw = statistics.median(m["return_pct"] for _, m, _ in rows)
            hold = statistics.median(h for _, _, h in rows)
            dd = statistics.median(m["max_drawdown_pct"] for _, m, _ in rows)
            tr = statistics.median(m["trades"] for _, m, _ in rows)
            print(f"{name:>28}{raw:>8.1f}{hold:>8.1f}{ex[0]:>11.1f}"
                  f"{statistics.median(ex):>12.1f}{ex[-1]:>10.1f}{dd:>8.1f}{tr:>8.0f}", flush=True)


if __name__ == "__main__":
    main()
