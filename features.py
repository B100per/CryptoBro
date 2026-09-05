"""Read the chart out of data.db and rank symbols.

    python3 features.py           # ranked table, binance.com futures universe
    python3 features.py --th      # the Binance TH spot board instead
    python3 features.py --json    # same, as JSON

Price structure comes from klines (full history, backfillable). Positioning
comes from the collector's own 30-min+ history, so those terms stay near zero
until the collector has been running a while. Nothing here places orders.
"""
import json
import sqlite3
import sys

import regime

DB = "data.db"


def ema(vals, n):
    k = 2 / (n + 1)
    out = vals[0]
    for v in vals[1:]:
        out = v * k + out * (1 - k)
    return out


def atr(highs, lows, closes, n=14):
    """Average true range over the last n bars; the volatility unit everything else divides by."""
    trs = [max(h - l, abs(h - pc), abs(l - pc))
           for h, l, pc in zip(highs[-n:], lows[-n:], closes[-n - 1:-1])]
    return sum(trs) / len(trs) if trs else 0.0


def structure(highs, lows, seg=12):
    """+1 when the last two segments made a higher high and a higher low, -1 for the mirror."""
    if len(highs) < seg * 2:
        return 0.0
    a_h, b_h = max(highs[-seg * 2:-seg]), max(highs[-seg:])
    a_l, b_l = min(lows[-seg * 2:-seg]), min(lows[-seg:])
    if b_h > a_h and b_l > a_l:
        return 1.0
    if b_h < a_h and b_l < a_l:
        return -1.0
    return 0.0


def clip(x, lo=-2.0, hi=2.0):
    return max(lo, min(hi, x))


def chart_read(bars):
    """bars: list of (open, high, low, close, volume), oldest first."""
    highs = [b[1] for b in bars]
    lows = [b[2] for b in bars]
    closes = [b[3] for b in bars]
    a = atr(highs, lows, closes)
    if a <= 0 or len(closes) < 60:
        return None
    name, tradable, detail = regime.classify(highs, lows, closes)
    return {
        "close": closes[-1],
        "atr_pct": a / closes[-1] * 100,
        "trend": clip((ema(closes, 20) - ema(closes, 50)) / a),
        "pullback": clip((closes[-1] - ema(closes, 20)) / a),
        "structure": structure(highs, lows),
        "regime": name,
        "tradable": tradable,
        "efficiency_ratio": detail["efficiency_ratio"],
        "atr_percentile": detail["atr_percentile"],
    }


def score(chart, pos, gate=True):
    """Trend-following, minus crowding. Positive = uptrend that the crowd has not piled into.

    A chart in chop scores below anything the planner will buy: refusing to
    act is the point of measuring the regime.
    """
    if gate and not chart.get("tradable", True):
        return -99.0
    s = 1.0 * chart["trend"] + 0.5 * chart["structure"]
    if pos:
        # funding above ~0.05% per 8h means longs are paying up: crowded, fade the enthusiasm
        s -= clip(pos["funding"] / 0.0005, -1.5, 1.5)
        # smart money leaning long while retail does not is the divergence worth paying for
        s += clip((pos["top_pos"] - pos["global_acct"]) / 0.5, -1.0, 1.0)
        s += clip(pos["oi_change"] / 2.0, -1.0, 1.0) * (1 if chart["trend"] > 0 else -1)
    return s


def load(db, lookback_bars=200, table="klines"):
    out = {}
    for (sym,) in db.execute(f"SELECT DISTINCT symbol FROM {table}"):
        bars = db.execute(
            f"SELECT open, high, low, close, volume FROM {table} WHERE symbol=? "
            "ORDER BY ts DESC LIMIT ?", (sym, lookback_bars)).fetchall()
        chart = chart_read(bars[::-1])
        if not chart:
            continue
        hist = db.execute(
            "SELECT funding, oi, top_pos, global_acct FROM positioning WHERE symbol=? "
            "ORDER BY ts DESC LIMIT 12", (sym,)).fetchall()
        pos = None
        if hist:
            f, oi, tp, ga = hist[0]
            oldest_oi = hist[-1][1]
            pos = {"funding": f, "top_pos": tp, "global_acct": ga,
                   "oi_change": (oi / oldest_oi - 1) * 100 if oldest_oi else 0.0}
        out[sym] = {"chart": chart, "pos": pos, "score": score(chart, pos)}
    return out


def main():
    db = sqlite3.connect(DB)
    table = "th_klines" if "--th" in sys.argv else "klines"
    ranked = sorted(load(db, table=table).items(),
                    key=lambda kv: kv[1]["score"], reverse=True)
    if "--json" in sys.argv:
        print(json.dumps(dict(ranked), indent=2))
        return
    print(f"{'symbol':<14}{'score':>7}{'trend':>7}{'struct':>7}{'ER':>6}"
          f"{'volpct':>8}{'regime':>10}{'fund%':>8}")
    for sym, d in ranked[:20]:
        c, p = d["chart"], d["pos"] or {}
        print(f"{sym:<14}{d['score']:>7.2f}{c['trend']:>7.2f}{c['structure']:>7.1f}"
              f"{c['efficiency_ratio']:>6.2f}{c['atr_percentile']:>8.2f}"
              f"{c['regime']:>10}{p.get('funding', 0) * 100:>8.4f}")


if __name__ == "__main__":
    main()
