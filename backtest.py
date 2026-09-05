"""Walk-forward backtest of the rule trade.py actually follows.

Not a per-symbol study: it rebalances a portfolio into the top-scoring coins
exactly the way the planner does, so the result answers the question that
matters, "would this rule have made money", rather than a different one.

    python3 backtest.py                    # all symbols in data.db
    python3 backtest.py --th               # only what Binance TH lists
    python3 backtest.py --fee 0.001 --top 5 --rebalance 12

Scores use price structure only. The positioning terms (funding, open
interest, top-trader divergence) cannot be backtested yet: Binance serves just
30 days of that data and the collector has only been running since 2026-09-04.
"""
import math
import sqlite3
import statistics
import sys

from features import chart_read, score

from book import STABLES, is_stable_pair   # noqa: F401  (shared with paper.py and the cloud step)

BARS_PER_YEAR = 365 * 24 * 12   # 5m bars
WINDOW = 200                    # bars of history each score is computed on


def load_bars(db, symbols=None, table="klines"):
    # taker_buy_base is the part of each bar's volume that hit the ask: the
    # buyers who crossed the spread. Its share of volume is the closest thing
    # to order flow the kline history carries.
    q = (f"SELECT symbol, ts, open, high, low, close, volume, taker_buy_base "
         f"FROM {table} ORDER BY ts")
    out = {}
    for sym, ts, o, h, l, c, v, tb in db.execute(q):
        if symbols and sym not in symbols:
            continue
        out.setdefault(sym, []).append((ts, o, h, l, c, v, tb))
    return out


def chart_signal(rows, i, window=WINDOW):
    """The rule the bot ships with: read the chart, score its structure."""
    chart = chart_read([(r[1], r[2], r[3], r[4], r[5]) for r in rows[i - window:i + 1]])
    return score(chart, None) if chart else None


def run(bars, top=5, rebalance=12, fee=0.001, min_score=0.5, start_equity=1000.0,
        score_fn=chart_signal, window=WINDOW, min_quote_vol=0.0,
        min_breadth=0.0, breadth_bars=288, exit_fn=None):
    """Equal-weight the top `top` scorers, rebalancing every `rebalance` bars.

    Cash and holdings are tracked separately, so equity is always a sum of two
    things you can point at rather than a running figure that drifts.
    """
    stamps = sorted({ts for rows in bars.values() for ts, *_ in rows})
    index = {sym: {r[0]: i for i, r in enumerate(rows)} for sym, rows in bars.items()}

    cash = start_equity
    units = {}       # symbol -> units held
    entry = {}       # symbol -> price paid, for per-trade pnl
    last = {}        # symbol -> last price seen, so a holding is never valued at zero
    curve, trades = [], []

    for step in range(WINDOW, len(stamps), rebalance):
        now = stamps[step]
        prices, scores = {}, {}
        for sym, rows in bars.items():
            i = index[sym].get(now)
            if i is None or i < window:
                continue
            last[sym] = rows[i][4]
            if is_stable_pair(sym):
                continue
            # A price you cannot trade at is not a price. Thin books are
            # where a backtest quietly books fills the exchange would refuse.
            if min_quote_vol:
                vol = sorted(r[5] * r[4] for r in rows[max(0, i - 288):i])
                if not vol or vol[len(vol) // 2] < min_quote_vol:
                    continue
            sc = score_fn(rows, i, window)
            if sc is None:
                continue
            prices[sym] = rows[i][4]
            scores[sym] = sc

        # A holding whose chart could not be read this step is still worth
        # something. Valuing it at zero is how a stablecoin position erased the
        # entire portfolio in one line.
        held_value = sum(u * last.get(s, 0.0) for s, u in units.items())
        if not prices:
            continue
        equity = cash + held_value
        curve.append((now, equity))
        if equity <= 0:
            break

        picks = [s for s, sc in sorted(scores.items(), key=lambda kv: -kv[1])
                 if sc >= min_score][:top]

        # Long-only has one answer to a falling market: do not be in it. When
        # fewer than min_breadth of the coins that could be scored are above
        # where they were breadth_bars ago, sit in USDT and buy nothing.
        if min_breadth and picks:
            up = tot = 0
            for sym in prices:
                rows, i = bars[sym], index[sym][now]
                if i >= breadth_bars and rows[i - breadth_bars][4] > 0:
                    tot += 1
                    up += rows[i][4] > rows[i - breadth_bars][4]
            if tot and up / tot < min_breadth:
                picks = []
        # A coin that merely slipped out of the top ranks is kept while its own
        # trend holds and sold only when exit_fn says the trend broke, because
        # rotating a rising coin out for a fee is the churn the fee analysis
        # kept finding. Without exit_fn, out of the ranks means out.
        def should_exit(sym):
            if sym in picks:
                return False
            if exit_fn is None or sym not in index or now not in index[sym]:
                return True
            return bool(exit_fn(bars[sym], index[sym][now]))

        # Kept coins still take their share of the book, or the freed cash
        # would be split over fewer names and buy the new picks oversized.
        kept = [s for s in units if s not in picks and s in last and not should_exit(s)]
        target = equity / (len(picks) + len(kept)) if picks else 0.0

        # Exit at the last known price, whether or not the chart was readable:
        # a position you cannot score is a position you especially want to close.
        for sym in [s for s in list(units) if s in last and should_exit(s)]:
            value = units.pop(sym) * last[sym]
            cash += value * (1 - fee)
            bought = entry.pop(sym, last[sym])
            trades.append({"symbol": sym, "pnl": value * (1 - fee) - bought})

        for sym in picks:
            have = units.get(sym, 0.0) * prices[sym]
            delta = target - have
            if abs(delta) < equity * 0.01:      # not worth the fee to nudge
                continue
            if delta > 0 and cash < delta * (1 + fee):
                delta = max(0.0, cash / (1 + fee))
            if delta == 0:
                continue
            cash -= delta + abs(delta) * fee
            units[sym] = units.get(sym, 0.0) + delta / prices[sym]
            entry[sym] = entry.get(sym, 0.0) + delta + abs(delta) * fee

    final = curve[-1][1] if curve else start_equity
    return metrics(curve, trades, start_equity), curve, trades, final


def hold_return(bars, fee=0.001, quote="USDT"):
    """Equal-weight buy at the first bar, sell at the last. The do-nothing return.

    Every strategy number is unreadable without it: +86% in a window where the
    board itself paid +120% is a loss dressed as a win.
    """
    rets = []
    for sym, rows in bars.items():
        if not sym.endswith(quote) or is_stable_pair(sym, quote) or len(rows) < 2:
            continue
        first, last = rows[0][4], rows[-1][4]
        if first > 0:
            rets.append(last * (1 - fee) / (first * (1 + fee)) - 1.0)
    return sum(rets) / len(rets) * 100 if rets else 0.0


def robust(bars, offsets=5, **kw):
    """Run the same rule at several start times and report the spread.

    Shifting the schedule by a few hours changes nothing a trader could name,
    so if the return swings across offsets, the result is luck of timing. A
    single backtest number hides that; this makes it the headline.
    """
    step = max(1, kw.get("rebalance", 12) // offsets)
    out = []
    for i in range(offsets):
        off = i * step
        shifted = {s: r[off:] for s, r in bars.items() if len(r) > off}
        m, _, _, _ = run(shifted, **kw)
        out.append((off, m, hold_return(shifted, kw.get("fee", 0.001))))
    return out


def metrics(curve, trades, start_equity):
    if len(curve) < 2:
        return {"bars": 0}
    eq = [e for _, e in curve]
    rets = [(b - a) / a for a, b in zip(eq, eq[1:]) if a > 0]

    peak, max_dd = eq[0], 0.0
    for v in eq:
        peak = max(peak, v)
        max_dd = max(max_dd, (peak - v) / peak if peak else 0.0)

    wins = [t for t in trades if t["pnl"] > 0]
    losses = [t for t in trades if t["pnl"] < 0]
    gross_win = sum(t["pnl"] for t in wins)
    gross_loss = abs(sum(t["pnl"] for t in losses))

    sharpe = 0.0
    if len(rets) > 1 and statistics.stdev(rets) > 0:
        # rebalance steps, not bars, are the sampling interval of this curve
        step_ms = max(1, curve[1][0] - curve[0][0])
        per_year = 365 * 24 * 3600 * 1000 / step_ms
        sharpe = statistics.mean(rets) / statistics.stdev(rets) * math.sqrt(per_year)

    return {
        "steps": len(curve),
        "return_pct": (eq[-1] - start_equity) / start_equity * 100,
        "max_drawdown_pct": max_dd * 100,
        "sharpe": sharpe,
        "trades": len(trades),
        "win_rate_pct": len(wins) / len(trades) * 100 if trades else 0.0,
        "profit_factor": gross_win / gross_loss if gross_loss else float("inf") if gross_win else 0.0,
    }


def main():
    def arg(name, default, cast=float):
        return cast(sys.argv[sys.argv.index(name) + 1]) if name in sys.argv else default

    db = sqlite3.connect("data.db")
    symbols = None
    if "--th" in sys.argv:
        from binance_th import tradable_here
        symbols = set(tradable_here()[0])

    table = sys.argv[sys.argv.index("--table") + 1] if "--table" in sys.argv else (
        "th_klines" if "--th-spot" in sys.argv else "klines")
    bars = load_bars(db, symbols, table)
    print(f"table={table} symbols={len(bars)} bars={sum(len(v) for v in bars.values()):,}")
    kw = dict(top=arg("--top", 5, int), rebalance=arg("--rebalance", 12, int),
              fee=arg("--fee", 0.001), min_score=arg("--min-score", 0.5))
    if "--robust" in sys.argv:
        rows = robust(bars, offsets=arg("--offsets", 5, int), **kw)
        print(f"\n{'start':>8}{'return%':>10}{'hold%':>9}{'excess%':>10}"
              f"{'maxDD%':>9}{'sharpe':>8}{'trades':>8}")
        for off, m, hold in rows:
            print(f"{off:>5}bar{m['return_pct']:>10.1f}{hold:>9.1f}"
                  f"{m['return_pct'] - hold:>10.1f}{m['max_drawdown_pct']:>9.1f}"
                  f"{m['sharpe']:>8.2f}{m['trades']:>8}")
        ex = sorted(m["return_pct"] - h for _, m, h in rows)
        print(f"\nexcess over buy-and-hold: median {statistics.median(ex):.1f}%, "
              f"worst {ex[0]:.1f}%, best {ex[-1]:.1f}%")
        # The spread is the finding. A rule whose worst start time loses is a
        # rule you cannot size, however good its median looks.
        print("verdict: " + ("timing luck, not an edge" if ex[0] < 0 else
                             "positive at every start time"))
        return
    m, curve, trades, final = run(
        bars, **kw)
    if not curve:
        print("not enough history to score anything")
        return
    hold = hold_return(bars, kw["fee"])
    print(f"period: {len(curve)} rebalances, 1000 -> {final:.2f}")
    print(f"buy-and-hold over the same window: {hold:.1f}%, "
          f"excess {m['return_pct'] - hold:+.1f}%\n")
    for k, v in m.items():
        print(f"  {k:<20} {v:,.2f}" if isinstance(v, float) else f"  {k:<20} {v}")


if __name__ == "__main__":
    main()
