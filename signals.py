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


def volume_surge(recent=12, baseline=288, min_ratio=3.0):
    """Buy what is suddenly being bought: volume far above its own normal, with
    price already moving up on it.

    A quiet coin that nobody trades is not interesting. A quiet coin whose
    turnover just went 3x with price rising is — that is what a crowd arriving
    looks like. Everything is measured against the coin's OWN history, so a
    thin book can qualify by waking up rather than by being big.

    The known failure: this is also exactly what the top of a pump looks like.
    A backtest fills at the close; a real order on a thin book pays the spread
    and moves the price, so judge this rule with a volume floor as well.
    """
    def fn(rows, i, window=None):
        if i < recent + baseline:
            return None
        base = sorted(r[5] * r[4] for r in rows[i - recent - baseline:i - recent])
        norm = base[len(base) // 2]
        if norm <= 0:
            return None
        now = sum(r[5] * r[4] for r in rows[i - recent + 1:i + 1]) / recent
        ratio = now / norm
        r = _returns(rows, i, recent)
        if r is None or r <= 0 or ratio < min_ratio:
            return -1.0          # not buyable; keeps the coin out of the ranking
        # rising on a surge: rank by how much of both
        return ratio * r
    fn.__name__ = f"surge_{recent}_{baseline}"
    return fn


def trend_broken(ema_bars=96, flow_bars=12, flow_floor=0.5):
    """Has this coin's own rise ended? Two witnesses must agree.

    Price: the close is under its EMA over `ema_bars` — the trend the coin was
    bought for has rolled over. Flow: over the last `flow_bars`, less than
    `flow_floor` of the volume was buyers crossing the spread, so the people
    still trading it are mostly selling. One alone is a dip; both together is
    an exit. If the bars carry no taker data, price decides on its own.
    """
    def fn(rows, i):
        if i < ema_bars:
            return False
        k = 2.0 / (ema_bars + 1)
        ema = rows[i - ema_bars][4]
        for j in range(i - ema_bars + 1, i + 1):
            ema += k * (rows[j][4] - ema)
        under = rows[i][4] < ema
        # No flow data, or flow switched off: price decides alone. (A floor of
        # 0 used to make "sellers" impossible, so nothing was ever sold.)
        if flow_floor <= 0 or len(rows[i]) < 7 or rows[i][6] is None:
            return under
        vol = sum(r[5] for r in rows[i - flow_bars + 1:i + 1])
        buy = sum(r[6] or 0.0 for r in rows[i - flow_bars + 1:i + 1])
        sellers = vol > 0 and buy / vol < flow_floor
        return under and sellers
    fn.__name__ = f"trend_broken_{ema_bars}"
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
    # Surge: same climb, but the last hour's volume is 5x the norm — that ranks;
    # the same climb at normal volume does not, and a surge on a FALLING price
    # is never bought.
    quiet = [(j * 300000, 100 + j, 101 + j, 99 + j, 100 + j, 10.0) for j in range(400)]
    loud = quiet[:388] + [(t, o, h, l, c, 50.0) for t, o, h, l, c, _ in quiet[388:]]
    dump = quiet[:388] + [(t, 100, 100, 90, 90 - k, 50.0)
                          for k, (t, *_r) in enumerate(quiet[388:])]
    surge = volume_surge(recent=12, baseline=288, min_ratio=3.0)
    assert surge(loud, 399) > 0, surge(loud, 399)
    assert surge(quiet, 399) < 0, "normal volume must not qualify"
    assert surge(dump, 399) < 0, "a surge while falling is a dump, never a buy"
    assert surge(loud, 100) is None, "not enough history must be skipped"
    # trend_broken: a rising coin is never "broken"; a coin that rolled under
    # its EMA with sellers dominating is; the same roll-over with buyers still
    # crossing the spread is only a dip.
    tb = trend_broken(ema_bars=48, flow_bars=12)
    rise = [(j * 300000, 100 + j, 101 + j, 99 + j, 100 + j, 10.0, 6.0) for j in range(200)]
    assert tb(rise, 199) is False
    roll = rise[:150] + [(t, 250 - 2 * k, 250 - 2 * k, 240 - 2 * k, 245 - 2 * k, 10.0, 3.0)
                         for k, (t, *_r) in enumerate(rise[150:])]
    assert tb(roll, 199) is True, "under EMA with sellers dominant must exit"
    dip = [r[:6] + (7.0,) for r in roll]                    # same price, buyers 70%
    assert tb(dip, 199) is False, "buyers still crossing the spread is a dip, not an exit"
    bare = [r[:6] for r in roll]                             # no taker column
    assert tb(bare, 199) is True, "without flow data, price alone decides"
    price_only = trend_broken(ema_bars=48, flow_bars=12, flow_floor=0.0)
    assert price_only(dip, 199) is True, "flow off must mean price decides, not never-sell"
    print("ok")


if __name__ == "__main__":
    demo()
