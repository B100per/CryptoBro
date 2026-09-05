"""Does a stop-loss between rebalances help the two rules that survived?

    python3 lab_stop.py > lab_stop.out                  # 12h rebalance, what runs today
    python3 lab_stop.py --rebalance 432 >> lab_stop.out # 36h, where lab_lean found the edge

Same yardstick as lab.py: worst case across start times, as excess over
buy-and-hold, on coins with real volume. A stop sells at the first 5m close
below (1 - stop) of average cost, any time between the 12-hourly rebalances.
Stop 0 is the rule as it runs today.
"""
import sqlite3
import statistics
import sys

import signals
from backtest import chart_signal, load_bars, robust

STOPS = (0.0, 0.05, 0.10, 0.15, 0.20)
RULES = [  # name, score_fn, min_score, window, min_breadth
    ("chart + breadth 60%", chart_signal, 0.5, 200, 0.6),
    ("vol-scaled mom 7d", signals.vol_scaled_momentum(2016), 0.0, 2016, 0.0),
]


def main():
    vol = float(sys.argv[sys.argv.index("--vol") + 1]) if "--vol" in sys.argv else 2000.0
    reb = int(sys.argv[sys.argv.index("--rebalance") + 1]) if "--rebalance" in sys.argv else 144
    bars = load_bars(sqlite3.connect("data.db"), None, "th_klines")
    print(f"symbols={len(bars)} bars={sum(len(v) for v in bars.values()):,} "
          f"min_quote_vol={vol:,.0f} rebalance={reb} ({reb / 12:g}h), 5 start times", flush=True)
    print(f"\n{'rule':>20}{'stop':>7}{'worst%':>9}{'median%':>10}{'best%':>9}{'maxDD%':>8}{'trades':>8}{'stops':>7}")
    for name, fn, floor, window, breadth in RULES:
        for stop in STOPS:
            rows = robust(bars, offsets=5, top=5, rebalance=reb, fee=0.001, min_score=floor,
                          score_fn=fn, window=window, min_quote_vol=vol,
                          min_breadth=breadth, stop_loss=stop)
            ex = sorted(m["return_pct"] - h for _, m, h in rows)
            dd = statistics.median(m["max_drawdown_pct"] for _, m, _ in rows)
            tr = statistics.median(m["trades"] for _, m, _ in rows)
            print(f"{name:>20}{stop:>7.0%}{ex[0]:>9.1f}{statistics.median(ex):>10.1f}"
                  f"{ex[-1]:>9.1f}{dd:>8.1f}{tr:>8.0f}{'':>7}", flush=True)


if __name__ == "__main__":
    main()
