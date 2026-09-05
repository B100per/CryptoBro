"""Compare ranking rules under one yardstick: the worst case, not the best.

Every rule is run at several start times and scored as excess over simply
holding the board. The headline is the WORST of those, because a rule that
only pays when you happen to switch it on at the right hour is not a rule,
it is a coin flip you have already called.

    python3 lab.py                 # every signal, two rebalance periods
    python3 lab.py --vol 50000     # only coins with real volume behind them

Read the columns, not one number. A signal worth keeping is positive across
start times AND across rebalance periods. One tall result beside two poor ones
is the same timing luck this harness exists to expose.
"""
import sqlite3
import statistics
import sys

import signals
from backtest import chart_signal, load_bars, robust

REBALANCES = (144, 432)          # 12h and 36h
OFFSETS = 5


def rules():
    yield "chart (current)", chart_signal, 0.5, 200
    for lb in (288, 2016, 8640):   # 1 day, 1 week, 30 days
        yield f"momentum {lb // 288}d", signals.momentum(lb), 0.0, lb
        yield f"vol-scaled mom {lb // 288}d", signals.vol_scaled_momentum(lb), 0.0, lb
    yield "reversal 1d", signals.reversal(288), 0.0, 288
    yield "breakout 1w", signals.breakout(2016), -0.02, 2016


def main():
    vol = float(sys.argv[sys.argv.index("--vol") + 1]) if "--vol" in sys.argv else 0.0
    bars = load_bars(sqlite3.connect("data.db"), None, "th_klines")
    print(f"symbols={len(bars)} bars={sum(len(v) for v in bars.values()):,} "
          f"min_quote_vol={vol:,.0f}")
    head = f"{'signal':>18}{'rebal':>7}{'worst%':>9}{'median%':>10}{'best%':>9}{'trades':>8}"
    print("\nexcess over buy-and-hold, across " + str(OFFSETS) + " start times\n" + head)
    for name, fn, floor, window in rules():
        for reb in REBALANCES:
            rows = robust(bars, offsets=OFFSETS, top=5, rebalance=reb, fee=0.001,
                          min_score=floor, score_fn=fn, window=window,
                          min_quote_vol=vol)
            ex = sorted(m["return_pct"] - h for _, m, h in rows)
            tr = statistics.median(m["trades"] for _, m, _ in rows)
            print(f"{name:>18}{reb:>7}{ex[0]:>9.1f}{statistics.median(ex):>10.1f}"
                  f"{ex[-1]:>9.1f}{tr:>8.0f}", flush=True)


if __name__ == "__main__":
    main()
