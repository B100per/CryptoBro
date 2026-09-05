"""The paper book's arithmetic, with no I/O in it.

paper.py (sqlite, on this machine) and cloud/functions/main.py (Firestore, on
Firebase) both call these. One implementation of "what does a rebalance do"
is the only way the two can be trusted to be the same strategy.
"""

# Pegged against the quote currency, so they cannot trend and must never be
# bought. One of them, USDP, once erased a backtest portfolio: a flat price
# gives zero ATR, chart_read returns None, and the holding vanished.
STABLES = {"USDC", "USDP", "TUSD", "FDUSD", "USD1", "DAI", "USDE", "RLUSD",
           "XUSD", "FRAX", "USDT", "BUSD", "PYUSD"}


def is_stable_pair(symbol, quote="USDT"):
    return symbol.endswith(quote) and symbol[: -len(quote)] in STABLES


def select(scores, prices, top, min_score):
    """The top `top` symbols by score that clear min_score and have a price."""
    return [s for s, v in sorted(scores.items(), key=lambda kv: -kv[1])
            if v >= min_score and s in prices][:top]


def rebalance(cash, held, prices, picks, now, fee=0.001, nudge=0.02):
    """Equal-weight the book into `picks`, selling what is no longer picked.

    held: {symbol: (units, entry_price)}. Returns (cash, held, fills) where
    fills are (ts, side, symbol, units, price, fee_paid). Pure: nothing here
    reads a clock, a network, or a database.
    """
    held = dict(held)
    fills = []
    holdings = sum(u * prices[s] for s, (u, _) in held.items() if s in prices)
    equity = cash + holdings
    target = equity / len(picks) if picks else 0.0

    for sym, (units, _) in list(held.items()):
        if sym in picks or sym not in prices:
            continue
        proceeds = units * prices[sym]
        cash += proceeds * (1 - fee)
        del held[sym]
        fills.append((now, "SELL", sym, units, prices[sym], proceeds * fee))

    for sym in picks:
        have = held.get(sym, (0.0, 0.0))[0] * prices[sym]
        delta = target - have
        if abs(delta) < equity * nudge:      # not worth the fee to nudge
            continue
        if delta > 0:
            delta = min(delta, max(0.0, cash / (1 + fee)))
            if delta <= 0:
                continue
        cash -= delta + abs(delta) * fee
        units = held.get(sym, (0.0, 0.0))[0] + delta / prices[sym]
        held[sym] = (units, prices[sym])
        fills.append((now, "BUY" if delta > 0 else "SELL", sym,
                      abs(delta) / prices[sym], prices[sym], abs(delta) * fee))

    # Float noise leaves cash at -5e-14 after spending it all. Round it away so
    # the stored balance is honest, but keep it signed so a real overdraft shows.
    return round(cash, 8), held, fills


def stop_out(cash, held, prices, stop, now, fee=0.001):
    """Sell every holding priced at or below (1 - stop) of its entry.

    Runs between rebalances, on live prices, so a crash is met within minutes
    instead of at the next scheduled step. stop=0 disables it. Same return
    shape as rebalance; a coin that has no price is left alone.
    """
    held = dict(held)
    fills = []
    if not stop:
        return cash, held, fills
    for sym, (units, entry) in list(held.items()):
        px = prices.get(sym)
        if px is None or px > entry * (1 - stop):
            continue
        proceeds = units * px
        cash += proceeds * (1 - fee)
        del held[sym]
        fills.append((now, "STOP", sym, units, px, proceeds * fee))
    return round(cash, 8), held, fills


def value(cash, held, prices):
    holdings = sum(u * prices[s] for s, (u, _) in held.items() if s in prices)
    return cash, holdings, cash + holdings


def demo():
    px = {"AAAUSDT": 10.0, "BBBUSDT": 20.0, "CCCUSDT": 5.0}
    assert select({"AAAUSDT": 2, "BBBUSDT": 1.5, "CCCUSDT": 0.1, "ZZZUSDT": 9}, px, 2, 0.5) \
        == ["AAAUSDT", "BBBUSDT"]                       # no price → not pickable

    cash, held, fills = rebalance(1000.0, {}, px, ["AAAUSDT", "BBBUSDT"], now=1)
    assert cash >= 0 and set(held) == {"AAAUSDT", "BBBUSDT"} and len(fills) == 2
    _, _, eq = value(cash, held, px)
    assert 990 < eq < 1000, eq                          # only fees were lost

    # a coin dropping out is sold, the new one bought, and nothing is overdrawn
    cash, held, fills = rebalance(cash, held, px, ["AAAUSDT", "CCCUSDT"], now=2)
    assert "BBBUSDT" not in held and "CCCUSDT" in held and cash >= 0
    assert [f[1] for f in fills if f[2] == "BBBUSDT"] == ["SELL"]

    # no picks → everything sold to cash
    cash, held, fills = rebalance(cash, held, px, [], now=3)
    assert held == {} and cash > 980
    assert is_stable_pair("USDCUSDT") and not is_stable_pair("BTCUSDT")

    # stop-loss: a coin 15% under its entry is sold, one 10% under is kept,
    # a coin with no price is kept, and stop=0 touches nothing
    held = {"AAAUSDT": (10.0, 10.0), "BBBUSDT": (5.0, 20.0), "CCCUSDT": (1.0, 5.0)}
    px2 = {"AAAUSDT": 8.5, "BBBUSDT": 18.0}
    cash, after, fills = stop_out(100.0, held, px2, 0.15, now=4)
    assert set(after) == {"BBBUSDT", "CCCUSDT"} and [f[1] for f in fills] == ["STOP"]
    assert abs(cash - (100 + 85 * 0.999)) < 1e-9, cash
    assert stop_out(100.0, held, px2, 0.0, now=4) == (100.0, held, [])
    print("ok")


if __name__ == "__main__":
    demo()
