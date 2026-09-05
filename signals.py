"""Alternative ranking rules, so the signal can be tested instead of assumed.

Every one has the same shape as backtest.chart_signal: given a symbol's bars
and the index of "now", return a number to rank by, or None to skip. Higher is
better, and backtest.run only buys what clears min_score, so a rule that
returns a negative number for a falling coin will never buy one.

These are deliberately plain. The point is not to find a clever formula, it is
to have something to compare the chart reader against: a rule that cannot beat
plain momentum is not earning the complexity it costs.
"""
import statistics


def _returns(rows, i, lookback):
    a = rows[i - lookback][4]
    return None if a <= 0 else rows[i][4] / a - 1.0


def momentum(lookback):
    """Cross-sectional momentum: buy what has gone up most over `lookback` bars.

    The most replicated anomaly there is, and the honest baseline for anything
    fancier. Long-only, so a negative reading is simply not bought.
    """
    def fn(rows, i, window=None):
        return _returns(rows, i, lookback) if i >= lookback else None
    fn.__name__ = f"momentum_{lookback}"
    return fn


def vol_scaled_momentum(lookback):
    """Momentum per unit of noise. A 20% move through calm ranks above a 20%
    move through chaos, because the second is far likelier to be luck."""
    def fn(rows, i, window=None):
        if i < lookback:
            return None
        r = _returns(rows, i, lookback)
        if r is None:
            return None
        # Sample the path at ~288 points whatever the horizon. Volatility over
        # 30 days does not need 8,640 bars to estimate, and at 384 symbols a
        # step that cost 8,640 ops was the difference between minutes and hours.
        k = max(1, lookback // 288)
        steps = [rows[j][4] / rows[j - k][4] - 1.0
                 for j in range(i, i - lookback, -k) if rows[j - k][4] > 0]
        if len(steps) < 2:
            return None
        sd = statistics.pstdev(steps)
        return None if sd <= 0 else r / (sd * (len(steps) ** 0.5))
    fn.__name__ = f"volmom_{lookback}"
    return fn


def reversal(lookback):
    """The opposite bet: buy what fell hardest, expecting a bounce.

    Included because it is momentum's mirror. If both look profitable on this
    sample, the sample is telling us about noise, not about either rule.
    """
    def fn(rows, i, window=None):
        if i < lookback:
            return None
        r = _returns(rows, i, lookback)
        return None if r is None else -r
    fn.__name__ = f"reversal_{lookback}"
    return fn


def breakout(lookback):
    """Buy what is making new highs: price relative to the range it just left."""
    def fn(rows, i, window=None):
        if i < lookback:
            return None
        hi = max(r[2] for r in rows[i - lookback:i])
        return None if hi <= 0 else rows[i][4] / hi - 1.0
    fn.__name__ = f"breakout_{lookback}"
    return fn


def demo():
    up = [(j * 300000, 100 + j, 101 + j, 99 + j, 100 + j, 10.0) for j in range(300)]
    down = [(j * 300000, 400 - j, 401 - j, 399 - j, 400 - j, 10.0) for j in range(300)]

    assert momentum(100)(up, 200) > 0 and momentum(100)(down, 200) < 0
    assert reversal(100)(down, 200) > 0, "reversal must like a faller"
    assert momentum(100)(up, 50) is None, "not enough history must be skipped"

    # A steady climb is all signal and no noise, so scaling by volatility must
    # rank it above the same climb delivered in jerks.
    jerky = [(j * 300000, 100 + j, 101 + j, 99 + j,
              100 + j + (8 if j % 2 else -8), 10.0) for j in range(300)]
    assert vol_scaled_momentum(100)(up, 200) > vol_scaled_momentum(100)(jerky, 200)

    # Breakout: at a new high the reading is ~0, below the old range it is negative.
    assert breakout(100)(up, 200) > -0.02
    flat_then_drop = up[:250] + [(r[0], 90, 90, 90, 90, 10.0) for r in up[250:]]
    assert breakout(100)(flat_then_drop, 290) < 0
    print("ok")


if __name__ == "__main__":
    demo()
