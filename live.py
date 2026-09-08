"""Real money on the one rule that passed: vol-scaled momentum, 36 h, 15 % stop.

trade.py sends the chart rule. This sends the momentum rule, with the same
arithmetic the paper book runs (book.rebalance, book.stop_out), so the
account and paper_volmom.db can be compared step for step.

    python3 live.py                   # DRY RUN: the rebalance it would send now
    python3 live.py --live            # send it, after typing 'yes i am sure'
    python3 live.py --watch           # DRY RUN: what the stop-loss would sell now
    python3 live.py --watch --live    # send those sells, no prompt: it only ever
                                      # sells, so it can run on a 5-minute schedule
    python3 live.py --status          # the account as the rule sees it

Units come from the exchange, never from memory. Entry prices live in
live_volmom.db, written from the actual fills; a coin found in the account
without one is adopted at the current price and its stop measured from there.
Needs in .env: BINANCE_KEY / BINANCE_SECRET (a binance.th key: spot only, no
withdrawal, IP-restricted) and MAX_NOTIONAL_USDT, the hard cap on holdings.
Nothing is planned without the cap, and every order still passes
BinanceTH.order's minimum-notional, cap and daily-drawdown checks.

No real money has been traded through this file yet.
"""
import os
import sys
import time

import book
import journal
import notify
import paper
from binance_client import RiskError
from binance_th import BinanceTH

DB = os.environ.get("LIVE_DB", "live_volmom.db")
QUOTE = "USDT"
RULE = dict(rule="volmom", min_vol=2000)       # control.STRATEGIES' volmom book, knob for knob
TOP, MIN_SCORE, STOP, FEE = 5, 0.0, 0.15, 0.001


def client():
    c = BinanceTH()
    c.max_notional = float(os.environ.get("MAX_NOTIONAL_USDT", 0)) or None
    if c.max_notional is None:
        raise RiskError("MAX_NOTIONAL_USDT is not set; refusing to plan")
    c.filters("BTC" + QUOTE)                   # warm the filter cache
    return c


def held(c, db, px):
    """{pair: (units, entry)}: units from the account, entries from the book."""
    entries = {s: e for s, _, e, _ in db.execute("SELECT * FROM positions")}
    out = {}
    for asset, qty in c.balances().items():
        pair = asset + QUOTE
        if asset == QUOTE or pair not in c._filters or pair not in px:
            continue
        if qty * px[pair] < c.min_notional(pair):
            continue                           # dust: the exchange would refuse the sell
        out[pair] = (qty, entries.get(pair, px[pair]))
    return out


def plan(c, db, px, now, watch=False):
    """(picks, held, fills). Fills are book rows: (ts, side, pair, units, price, fee)."""
    h = held(c, db, px)
    if watch:
        _, _, fills = book.stop_out(0.0, h, px, STOP, now, fee=FEE)
        return [], h, fills
    sc, _ = paper.scores(**RULE)
    picks = book.select(sc, px, TOP, MIN_SCORE)
    room = c.max_notional - sum(u * px[s] for s, (u, _) in h.items())
    cash = min(c.balances().get(QUOTE, 0.0), max(0.0, room))
    _, _, fills = book.rebalance(cash, h, px, picks, now, fee=FEE)
    return picks, h, fills


def refusal(c, pair, units, price):
    """Why the exchange would refuse this order, or None."""
    qty = c.round_qty(pair, units)
    if qty <= 0:
        return "rounds to zero at this step size"
    if qty * price < c.min_notional(pair):
        return f"under the {c.min_notional(pair):.0f} {QUOTE} minimum"
    return None


def filled(res, units, price):
    """(units, average price) actually executed, or the plan if the reply has none."""
    q = float(res.get("executedQty") or 0)
    v = float(res.get("cummulativeQuoteQty") or 0)
    return (q, v / q) if q else (units, price)


def record(db, side, pair, units, price, now, whole):
    """Keep the book's entries in step with what was actually filled."""
    if side == "BUY":                          # a top-up re-marks the entry, as paper does
        db.execute("INSERT OR REPLACE INTO positions VALUES (?,?,?,?)", (pair, units, price, now))
    elif whole:
        db.execute("DELETE FROM positions WHERE symbol=?", (pair,))
    db.execute("INSERT INTO fills VALUES (?,?,?,?,?,?)",
               (now, side, pair, units, price, units * price * FEE))
    db.commit()


def mark(c, db, px, now):
    h = held(c, db, px)
    cash = c.balances().get(QUOTE, 0.0)
    _, holdings, equity = book.value(cash, h, px)
    db.execute("INSERT OR REPLACE INTO equity VALUES (?,?,?,?)", (now, cash, holdings, equity))
    db.commit()
    return cash, holdings, equity


def execute(c, db, fills, h, now, live):
    """Print the plan; with live, send it. Returns the rows sent (or that would be)."""
    rows = [(side, pair, units, units * price, refusal(c, pair, units, price))
            for _, side, pair, units, price, _ in fills]
    print(f"\n{'side':<6}{'pair':<12}{'qty':>16}{'value':>12}")
    for side, pair, units, value, why in rows:
        print(f"{side:<6}{pair:<12}{units:>16.8f}{value:>12.2f}" + (f"  skip: {why}" if why else ""))
    todo = [(s, p, u, v) for s, p, u, v, why in rows if not why]
    notify.orders(todo, QUOTE, live)
    if not live:
        print("\nDRY RUN. Nothing was sent.")
        for side, pair, units, value in todo:
            journal.record(side, pair, units, value / units, QUOTE, live=False)
        return todo
    for side, pair, units, value in todo:
        price = value / units
        try:
            res = c.order(pair, "SELL" if side == "STOP" else side, units, quote=QUOTE)
            q, px = filled(res, c.round_qty(pair, units), price)
            record(db, side, pair, q, px, now, whole=units >= h.get(pair, (0.0,))[0] * 0.999)
            journal.record(side, pair, q, px, QUOTE, live=True, order_id=res.get("orderId"))
            print(f"sent {side} {pair} {q} @ {px}")
        except Exception as e:
            print(f"refused: {side} {pair}: {e}")
            journal.record(side, pair, units, price, QUOTE, live=True, error=str(e))
            notify.send(f"Order failed: {side} {pair}", str(e), "bad")
    return todo


def main():
    live, watch = "--live" in sys.argv, "--watch" in sys.argv
    c = client()
    db = paper.db(DB)
    px = paper.prices()
    now = int(time.time() * 1000)
    if "--status" in sys.argv:
        cash, holdings, equity = mark(c, db, px, now)
        print(f"cash {cash:.2f} holdings {holdings:.2f} equity {equity:.2f} {QUOTE}")
        for pair, (units, entry) in sorted(held(c, db, px).items()):
            print(f"  {pair:<12}{units:>16.8f} @ {entry}  now {px[pair]}  "
                  f"stop {entry * (1 - STOP):.6g}")
        return
    picks, h, fills = plan(c, db, px, now, watch=watch)
    print(f"{'watch' if watch else 'rebalance'} cap={c.max_notional} "
          f"free={c.balances().get(QUOTE, 0.0):.2f} {QUOTE} "
          f"held={','.join(sorted(h)) or '-'} picks={','.join(picks) or '-'}")
    if not fills:
        print("nothing to do")
        mark(c, db, px, now)
        return
    if live and not watch:
        # The one prompt in the project: opening risk waits for a human. The
        # stop-loss watch does not; it can only sell, and a crash cannot wait.
        print(f"\nAbout to send {len(fills)} REAL orders on binance.th.")
        if input("Type EXACTLY 'yes i am sure' to continue: ").strip() != "yes i am sure":
            print("aborted")
            return
    execute(c, db, fills, h, now, live)
    if live:
        mark(c, db, px, now)


if __name__ == "__main__":
    main()
