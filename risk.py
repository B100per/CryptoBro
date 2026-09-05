"""Daily drawdown circuit breaker.

Ported from the Alpaca bot's RiskManager, minus the equities-only parts (PDT
limits, end-of-day flush, market hours: crypto never closes). One change that
matters: the anchor is persisted. The old version held it in memory, so a
restart forgot the day's starting equity and the breaker silently reset. A
service with Restart=always restarts exactly when things are going wrong.

    python3 risk.py    # show today's state
"""
import json
import os
import sys
import time

STATE_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "risk_state.json")
DEFAULT_LIMIT = 0.05   # halt buying after a 5% drop from the day's starting equity


def _today():
    return time.strftime("%Y-%m-%d", time.gmtime())


def load_state(path=None):
    path = path or STATE_FILE
    try:
        with open(path) as f:
            return json.load(f)
    except (FileNotFoundError, ValueError):
        return {}


def check(equity, limit=None, path=None, today=None):
    """Returns (allowed, reason, state). Call before every BUY.

    The trip is sticky for the rest of the UTC day: a bounce back above the
    threshold does not re-enable buying, because the point is to stop trading
    on a day that is already going badly, not to track the line continuously.
    """
    limit = DEFAULT_LIMIT if limit is None else limit
    path = path or STATE_FILE
    today = today or _today()
    state = load_state(path)

    if state.get("date") != today or not state.get("anchor"):
        state = {"date": today, "anchor": equity, "tripped": False}

    anchor = state["anchor"]
    dd = (anchor - equity) / anchor if anchor > 0 else 0.0
    state["drawdown"] = dd
    state["equity"] = equity

    if dd >= limit:
        state["tripped"] = True

    with open(path, "w") as f:
        json.dump(state, f, indent=2)

    if state["tripped"]:
        return False, (f"circuit breaker: down {dd:.2%} from {anchor:.2f} today, "
                       f"limit is {limit:.2%}. Selling is still allowed."), state
    return True, "", state


if __name__ == "__main__":
    s = load_state()
    if not s:
        print("no state yet; it is written on the first check()")
        sys.exit(0)
    print(f"date={s.get('date')} anchor={s.get('anchor', 0):.2f} "
          f"equity={s.get('equity', 0):.2f} drawdown={s.get('drawdown', 0):.2%} "
          f"tripped={s.get('tripped')}")
