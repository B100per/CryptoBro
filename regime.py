"""Is this market trending or just chopping around?

Trend following pays in a trend and bleeds in chop: every swing looks like a
signal, you pay the fee both ways, and the price ends where it started. The
90-day backtest made 5,533 trades to lose 91%, which is what that bleeding
looks like. So measure the difference and refuse to trade through the chop.

Efficiency ratio (Kaufman): distance travelled divided by ground covered.
A clean one-way move approaches 1. A market that ends where it began, having
thrashed the whole way, approaches 0.
"""

TREND_MIN = 0.30      # below this, price is going nowhere expensively
CALM_MAX = 0.80       # ATR percentile above this is a market worth standing clear of


def efficiency_ratio(closes, n=60):
    """Net movement over total movement across the last n bars, in [0, 1]."""
    window = closes[-(n + 1):]
    if len(window) < 3:
        return 0.0
    path = sum(abs(b - a) for a, b in zip(window, window[1:]))
    return abs(window[-1] - window[0]) / path if path else 0.0


def percentile(values, value):
    """Where `value` sits within `values`, in [0, 1]."""
    if not values:
        return 0.5
    return sum(1 for v in values if v <= value) / len(values)


def atr_percentile(highs, lows, closes, n=14, lookback=500):
    """Current ATR ranked against its own recent history, so it compares across coins."""
    from features import atr
    if len(closes) < n + 20:
        return 0.5
    now = atr(highs, lows, closes, n)
    if closes[-1] <= 0:
        return 0.5
    now_pct = now / closes[-1]

    history = []
    for end in range(n + 1, len(closes), max(1, (len(closes) - n) // min(lookback, 120))):
        c = closes[max(0, end - n - 1):end]
        h = highs[max(0, end - n - 1):end]
        l = lows[max(0, end - n - 1):end]
        if len(c) > n and c[-1] > 0:
            history.append(atr(h, l, c, n) / c[-1])
    return percentile(history, now_pct)


def classify(highs, lows, closes, trend_min=TREND_MIN, calm_max=CALM_MAX):
    """Returns (name, tradable, detail).

    `tradable` is the whole point: it gates whether the strategy acts at all.
    """
    er = efficiency_ratio(closes)
    vol = atr_percentile(highs, lows, closes)
    detail = {"efficiency_ratio": er, "atr_percentile": vol}

    if vol > calm_max:
        return "volatile", False, detail      # moves are real but stops get run over
    if er < trend_min:
        return "chop", False, detail          # the expensive nowhere
    return "trend", True, detail
