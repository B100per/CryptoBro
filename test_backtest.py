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
