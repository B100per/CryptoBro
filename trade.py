"""Turn the chart read into a spot plan for the Binance TH account.

Dry run by default: it prints the orders it would send and sends nothing.

    python3 trade.py                    # plan against THB pairs
    python3 trade.py --quote USDT       # plan against USDT pairs (21 candidates, needs USDT)
    python3 trade.py --live             # actually send, after a typed confirmation

Spot is long-only, so a negative score means "do not hold" rather than "short".
Signals come from binance.com futures data in data.db; execution is on
binance.th. Two different venues for the same asset.
"""
import sqlite3
import sys

import journal
import notify
from binance_client import RiskError
from binance_th import BinanceTH
from features import load

MIN_SCORE = 0.5   # below this a coin is not worth the round-trip fee
DB = "data.db"


def candidates(quote, filters, db_path=DB):
    """Ranked (pair, base, score) for coins we have a signal on and can buy here."""
    db = sqlite3.connect(db_path)
    out = []
    for sym, d in load(db).items():
        if not sym.endswith("USDT"):
            continue
        base = sym[: -len("USDT")]
        pair = base + quote
        if pair in filters and d["score"] >= MIN_SCORE:
            out.append((pair, base, d["score"]))
    return sorted(out, key=lambda r: r[2], reverse=True)


def plan(client, quote="THB"):
    """What to buy and what to sell, as (side, pair, qty, value) rows."""
    cap = client.max_notional
    if cap is None:
        raise RiskError(f"MAX_NOTIONAL_{quote} is not set; nothing to plan against")

    client.filters("BTC" + quote)          # warm the filter cache
    ranked = candidates(quote, client._filters)
    balances = client.balances()
    held = {a: q for a, q in balances.items() if a != quote}

    # Never plan to spend more than is actually sitting in the account, or the
    # orders come back rejected for insufficient balance.
    cap = min(cap, balances.get(quote, 0.0) + client.exposure(quote))

    # Equal weight, and never so many positions that each falls under the
    # exchange minimum. That minimum, not the cap, sets the ceiling on breadth.
    pairs = [p for p, _, _ in ranked] or [b + quote for b in ("BTC", "ETH")]
    floor = max(client.min_notional(p) for p in pairs if p in client._filters)
    slots = max(int(cap // floor), 0) if floor else 0
    picks = ranked[:slots]
    size = cap / len(picks) if picks else 0

    rows = []
    for base, qty in sorted(held.items()):
        pair = base + quote
        if pair not in client._filters or any(b == base for _, b, _ in picks):
            continue
        try:
            value = qty * client.price(pair)
        except Exception:
            continue
        if value >= client.min_notional(pair):
            rows.append(("SELL", pair, qty, value))   # held, no longer wanted

    for pair, base, score in picks:
        if base in held:
            continue                                   # already holding, leave it alone
        qty = client.round_qty(pair, size / client.price(pair))
        rows.append(("BUY", pair, qty, qty * client.price(pair)))
    return rows, ranked, slots


def main():
    quote = "USDT" if "--quote" in sys.argv and "USDT" in sys.argv else "THB"
    live = "--live" in sys.argv
    c = BinanceTH()
    if quote != "THB":
        import os
        c.max_notional = float(os.environ.get(f"MAX_NOTIONAL_{quote}", 0)) or None

    rows, ranked, slots = plan(c, quote)
    scores = {p: sc for p, _, sc in ranked}
    free = c.balances().get(quote, 0.0)
    print(f"quote={quote} cap={c.max_notional} free={free:.2f} "
          f"exposure={c.exposure(quote):.2f} slots={slots} candidates={len(ranked)}")
    if not rows:
        print("nothing to do")
        return
    print(f"\n{'side':<6}{'pair':<12}{'qty':>16}{'value':>12}")
    for side, pair, qty, value in rows:
        print(f"{side:<6}{pair:<12}{qty:>16.8f}{value:>12.2f}")

    notify.orders(rows, quote, live)

    if not live:
        print("\nDRY RUN. Nothing was sent. Add --live to place these orders.")
        for side, pair, qty, value in rows:
            journal.record(side, pair, qty, value / qty if qty else 0, quote,
                           score=scores.get(pair), live=False)
        return

    print(f"\nAbout to send {len(rows)} REAL orders on binance.th.")
    if input("Type EXACTLY 'yes i am sure' to continue: ").strip() != "yes i am sure":
        print("aborted")
        return
    for side, pair, qty, value in rows:
        price = value / qty if qty else 0
        try:
            res = c.order(pair, side, qty, quote=quote)
            print(side, pair, res)
            journal.record(side, pair, qty, price, quote, score=scores.get(pair),
                           live=True, order_id=res.get("orderId"))
        except Exception as e:
            print(f"refused: {e}")
            journal.record(side, pair, qty, price, quote, score=scores.get(pair),
                           live=True, error=str(e))
            notify.send(f"Order failed: {side} {pair}", str(e), "bad")


if __name__ == "__main__":
    main()
