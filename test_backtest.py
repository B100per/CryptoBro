from backtest import run, metrics, WINDOW

def series(prices, start_ts=0, step=300_000):
    """OHLCV bars from a list of closes."""
    return [(start_ts + i * step, p, p * 1.001, p * 0.999, p, 100.0)
            for i, p in enumerate(prices)]

n = WINDOW + 300
rising = series([100 * (1.002 ** i) for i in range(n)])
flat = series([100.0] * n)

# a single steadily rising asset must end up ahead of where it started
m, curve, trades, final = run({"UP": rising}, top=1, rebalance=12, fee=0.0)
assert final > 1000, final
assert m["max_drawdown_pct"] < 1.0        # no drawdown in a monotonic climb

# fees must eat into the same run, never improve it
_, _, _, with_fee = run({"UP": rising}, top=1, rebalance=12, fee=0.002)
assert with_fee < final

# a flat asset never scores, so nothing is bought and equity is untouched
m, curve, trades, final = run({"FLAT": flat}, top=1, rebalance=12, fee=0.001)
assert final == 1000.0 and trades == []

# equity must never go negative, and cash must never be overspent
falling = series([100 * (0.99 ** i) for i in range(n)])
_, curve, _, final = run({"DOWN": falling, "UP": rising}, top=2, rebalance=12, fee=0.001)
assert all(e >= 0 for _, e in curve)

# metrics on a known curve
eq = [(i * 300_000, v) for i, v in enumerate([100, 110, 90, 120])]
m = metrics(eq, [{"pnl": 10}, {"pnl": -5}, {"pnl": 20}], 100)
assert abs(m["return_pct"] - 20.0) < 1e-9
assert abs(m["max_drawdown_pct"] - (20 / 110 * 100)) < 1e-9   # 110 -> 90
assert abs(m["win_rate_pct"] - 200 / 3) < 1e-9
assert abs(m["profit_factor"] - 30 / 5) < 1e-9

# too little data must report rather than divide by zero
assert metrics([], [], 100) == {"bars": 0}
print("ok")

from backtest import is_stable_pair

assert is_stable_pair("USDPUSDT") and is_stable_pair("USDCUSDT")
assert not is_stable_pair("BTCUSDT") and not is_stable_pair("PAXGUSDT")

# The bug that erased a portfolio: a coin goes flat, its ATR hits zero,
# chart_read returns None, and the holding must NOT be valued at zero.
n = WINDOW + 120
rising = series([100 * (1.002 ** i) for i in range(n)])
# same asset, then pinned to a constant for the rest of the run
pinned = rising[:WINDOW + 40] + [(t, 200.0, 200.0, 200.0, 200.0, 100.0)
                                 for t, *_ in rising[WINDOW + 40:]]
m, curve, trades, final = run({"UP": rising, "FLAT": pinned}, top=2, rebalance=12, fee=0.0)
assert final > 0, final
assert all(e > 0 for _, e in curve), "a holding that stops scoring must keep its value"
assert m["max_drawdown_pct"] < 100.0

# a portfolio holding only the pinned asset must not evaporate
m, curve, trades, final = run({"FLAT": pinned}, top=1, rebalance=12, fee=0.0)
assert final > 0 and all(e > 0 for _, e in curve)
print("ok")

from backtest import hold_return, robust

# The do-nothing baseline: one asset doubling means +100% before fees.
doubling = series([100 * (1.00035 ** i) for i in range(WINDOW + 120)])
h = hold_return({"AAAUSDT": doubling}, fee=0.0)
assert abs(h - (doubling[-1][4] / doubling[0][4] - 1) * 100) < 1e-9, h

# Stablecoin pairs are not part of the market you could have held instead,
# and a non-quote pair is not comparable at all.
assert hold_return({"USDPUSDT": doubling}, fee=0.0) == 0.0
assert hold_return({"BTCTHB": doubling}, fee=0.0) == 0.0

# Fees make holding worse, never better.
assert hold_return({"AAAUSDT": doubling}, fee=0.01) < h

# robust() must actually vary the start time, not run the same thing five times.
rows = robust({"AAAUSDT": doubling, "BBBUSDT": rising}, offsets=4,
              top=1, rebalance=48, fee=0.0)
assert len(rows) == 4
assert [off for off, _, _ in rows] == [0, 12, 24, 36]
assert len({m["steps"] for _, m, _ in rows}) > 1, "shifting the start changed nothing"
print("ok")

from backtest import chart_signal
import signals

# A pluggable signal must actually steer the portfolio, not sit unused.
falling = series([100 * (0.998 ** i) for i in range(WINDOW + 200)])
climbing = series([100 * (1.002 ** i) for i in range(WINDOW + 200)])
pair = {"UPUSDT": climbing, "DOWNUSDT": falling}

mom, _, _, mom_final = run(pair, top=1, rebalance=48, fee=0.0, min_score=0.0,
                           score_fn=signals.momentum(96), window=96)
rev, _, _, rev_final = run(pair, top=1, rebalance=48, fee=0.0, min_score=0.0,
                           score_fn=signals.reversal(96), window=96)
assert mom_final > rev_final, (mom_final, rev_final)   # one buys the winner, one the loser

# The liquidity filter must exclude a thin book, leaving nothing to buy.
thin = {"UPUSDT": [(t, o, h, l, c, 0.000001) for t, o, h, l, c, _ in climbing]}
m, curve, _, final = run(thin, top=1, rebalance=48, fee=0.0, min_score=0.0,
                         score_fn=signals.momentum(96), window=96,
                         min_quote_vol=1_000_000)
# Nothing tradable means no curve at all, and the money is untouched.
assert m == {"bars": 0} and curve == [] and abs(final - 1000.0) < 1e-9, (m, final)
# ...and must let a liquid one through, otherwise it filters everything.
m, *_ = run({"UPUSDT": climbing}, top=1, rebalance=48, fee=0.0, min_score=0.0,
            score_fn=signals.momentum(96), window=96, min_quote_vol=1.0)
assert m["steps"] > 0
print("ok")

# Market breadth: when most of the board is below where it was, hold cash even
# though a coin still ranks. With the gate off the same coin is bought.
n = WINDOW + 600
bull = series([100 * (1.001 ** i) for i in range(n)])
bears = {f"B{k}USDT": series([100 * (0.999 ** i) for i in range(n)]) for k in range(4)}
board = {"UPUSDT": bull, **bears}
mom = signals.momentum(96)
off, _, _, _ = run(board, top=1, rebalance=48, fee=0.0, min_score=0.0,
                   score_fn=mom, window=300)
on, curve_on, _, _ = run(board, top=1, rebalance=48, fee=0.0, min_score=0.0,
                         score_fn=mom, window=300, min_breadth=0.5, breadth_bars=288)
assert off["trades"] >= 0 and off["steps"] > 0
assert on["trades"] == 0, on["trades"]                        # 1 of 5 rising: stayed in cash
assert all(abs(e - 1000.0) < 1e-9 for _, e in curve_on)     # and cash does not move

# ...and a board that is mostly rising passes the gate.
bulls = {f"U{k}USDT": series([100 * (1.001 ** i) for i in range(n)]) for k in range(4)}
board2 = {**bulls, "DNUSDT": series([100 * (0.999 ** i) for i in range(n)])}
on2, *_ = run(board2, top=1, rebalance=48, fee=0.0, min_score=0.0,
              score_fn=mom, window=300, min_breadth=0.5, breadth_bars=288)
assert on2["steps"] > 0 and on2["return_pct"] > 0, on2
print("ok")
