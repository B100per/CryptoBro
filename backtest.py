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

BARS_PER_YEAR = 365 * 24 * 12   # 5m bars
WINDOW = 200                    # bars of history each score is computed on


def load_bars(db, symbols=None):
    q = "SELECT symbol, ts, open, high, low, close, volume FROM klines ORDER BY ts"
    out = {}
    for sym, ts, o, h, l, c, v in db.execute(q):
        if symbols and sym not in symbols:
            continue
        out.setdefault(sym, []).append((ts, o, h, l, c, v))
    return out


def run(bars, top=5, rebalance=12, fee=0.001, min_score=0.5, start_equity=1000.0):
    """Equal-weight the top `top` scorers, rebalancing every `rebalance` bars.

    Cash and holdings are tracked separately, so equity is always a sum of two
    things you can point at rather than a running figure that drifts.
    """
    stamps = sorted({ts for rows in bars.values() for ts, *_ in rows})
    index = {sym: {r[0]: i for i, r in enumerate(rows)} for sym, rows in bars.items()}

    cash = start_equity
    units = {}       # symbol -> units held
    entry = {}       # symbol -> price paid, for per-trade pnl
    curve, trades = [], []

    for step in range(WINDOW, len(stamps), rebalance):
        now = stamps[step]
        prices, scores = {}, {}
        for sym, rows in bars.items():
            i = index[sym].get(now)
            if i is None or i < WINDOW:
                continue
            chart = chart_read([(r[1], r[2], r[3], r[4], r[5])
                                for r in rows[i - WINDOW:i + 1]])
            if not chart:
                continue
            prices[sym] = rows[i][4]
            scores[sym] = score(chart, None)

        # Anything held but not priced this step keeps its last known value.
        held_value = sum(u * prices[s] for s, u in units.items() if s in prices)
        if not prices:
            continue
        equity = cash + held_value
        curve.append((now, equity))
        if equity <= 0:
            break

        picks = [s for s, sc in sorted(scores.items(), key=lambda kv: -kv[1])
                 if sc >= min_score][:top]
        target = equity / len(picks) if picks else 0.0

        for sym in [s for s in units if s not in picks and s in prices]:
            value = units.pop(sym) * prices[sym]
            cash += value * (1 - fee)
            bought = entry.pop(sym, prices[sym])
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
        per_year = BARS_PER_YEAR / max(1, (curve[1][0] - curve[0][0]) // 300_000)
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

    bars = load_bars(db, symbols)
    print(f"symbols={len(bars)} bars={sum(len(v) for v in bars.values()):,}")
    m, curve, trades, final = run(
        bars, top=arg("--top", 5, int), rebalance=arg("--rebalance", 12, int),
        fee=arg("--fee", 0.001), min_score=arg("--min-score", 0.5))
    if not curve:
        print("not enough history to score anything")
        return
    print(f"period: {len(curve)} rebalances, 1000 -> {final:.2f}\n")
    for k, v in m.items():
        print(f"  {k:<20} {v:,.2f}" if isinstance(v, float) else f"  {k:<20} {v}")


if __name__ == "__main__":
    main()
