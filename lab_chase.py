"""Does refusing to chase a spike help the momentum rule?

    python3 lab_chase.py > lab_chase.out         # 36h, stop 15%, the book as it runs

On 2026-09-10 the rule bought IOST +152% in 7 days and +59% in the last day;
it lost 20% in 31 minutes. This keeps everything else as it runs (36 h,
15% stop, floor 2,000) and adds one gate: a coin whose return over the last
`bars` bars exceeds `cap` is not scored that step. cap None is today's rule.
Same yardstick as every lab: worst case across start times, excess over
buy-and-hold.
"""
import sqlite3
import statistics

import signals
from backtest import load_bars, robust

CAPS = (None, 1.00, 0.50, 0.25)
WINDOWS = (("1d", 288), ("3d", 864))


def no_chase(fn, cap, bars):
    if cap is None:
        return fn

    def f(rows, i, window=None):
        if i >= bars and rows[i - bars][4] > 0 and rows[i][4] / rows[i - bars][4] - 1 > cap:
            return None
        return fn(rows, i, window)
    return f


def main():
    bars = load_bars(sqlite3.connect("data.db"), None, "th_klines")
    print(f"symbols={len(bars)} bars={sum(len(v) for v in bars.values()):,} "
          f"rebalance=432 (36h) stop=15% floor=2,000, 5 start times", flush=True)
    print(f"\n{'window':>8}{'cap':>8}{'worst%':>9}{'median%':>10}{'best%':>9}{'maxDD%':>8}{'trades':>8}")
    base = signals.vol_scaled_momentum(2016)
    # (window, cap): the uncapped rule is the same whatever the window, so it
    # runs once. An earlier version broke out of the inner loop on cap None and
    # measured nothing else at all.
    runs = [("-", 288, None)] + [(n, w, c) for n, w in WINDOWS for c in CAPS if c]
    for name, w, cap in runs:
        rows = robust(bars, offsets=5, top=5, rebalance=432, fee=0.001, min_score=0.0,
                      score_fn=no_chase(base, cap, w), window=2016, min_quote_vol=2000,
                      min_breadth=0.0, stop_loss=0.15)
        ex = sorted(m["return_pct"] - h for _, m, h in rows)
        dd = statistics.median(m["max_drawdown_pct"] for _, m, _ in rows)
        tr = statistics.median(m["trades"] for _, m, _ in rows)
        print(f"{name:>8}{('none' if cap is None else f'{cap:.0%}'):>8}{ex[0]:>9.1f}"
              f"{statistics.median(ex):>10.1f}{ex[-1]:>9.1f}{dd:>8.1f}{tr:>8.0f}", flush=True)


if __name__ == "__main__":
    main()
