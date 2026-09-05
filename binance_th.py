"""Binance TH (binance.th) spot client.

A separate exchange from binance.com: different host, `/api/v1` paths, and
spot only. There is no futures market, so there is no funding, no open
interest and no long/short ratio here, and no way to short. Signals still
come from the binance.com futures data the collector gathers (public, no key
needed); this module only executes, long-only, on the Thai account.

    python3 binance_th.py            # balances and what the cap allows
    python3 binance_th.py --symbols  # pairs tradable here that we have signals for
"""
import json
import os
import sqlite3
import sys
import urllib.request

from binance_client import Binance, RiskError, load_env

BASE = "https://api.binance.th"
# Budget cap is in THB here, not USDT: this account is funded in baht.
CAP_ENV = "MAX_NOTIONAL_THB"


class BinanceTH(Binance):
    def __init__(self, key=None, secret=None, max_notional=None):
        super().__init__(key, secret, live=True, max_notional=1)  # cap replaced below
        self.base = BASE
        cap = os.environ.get(CAP_ENV) if max_notional is None else max_notional
        self.max_notional = float(cap) if cap not in (None, "") else None

    def filters(self, symbol):
        if self._filters is None:
            with urllib.request.urlopen(BASE + "/api/v1/exchangeInfo", timeout=10) as r:
                info = json.load(r)
            self._filters = {s["symbol"]: {f["filterType"]: f for f in s["filters"]}
                             for s in info["symbols"]}
        return self._filters[symbol]

    def min_notional(self, symbol):
        f = self.filters(symbol)
        n = f.get("NOTIONAL") or f.get("MIN_NOTIONAL") or {}
        return float(n.get("minNotional", 0))

    def account(self):
        return self.call("/api/v1/accountV2")

    def balances(self):
        return {b["asset"]: float(b["free"]) for b in self.account()["balances"]
                if float(b["free"]) > 0}

    def price(self, symbol):
        with urllib.request.urlopen(
                BASE + f"/api/v1/ticker/price?symbol={symbol}", timeout=10) as r:
            return float(json.load(r)["price"])

    def exposure(self, quote="THB"):
        """Value of everything held that is not the quote currency itself.

        Spot has no positions, only holdings, so exposure is what you own that
        can still move against you.
        """
        total = 0.0
        for asset, free in self.balances().items():
            if asset == quote:
                continue
            try:
                total += free * self.price(asset + quote)
            except Exception:
                continue  # not tradable against this quote; ignore rather than guess
        return total

    def order(self, symbol, side, qty, client_id=None, price=None, quote="THB"):
        """Market order, refused if it would take holdings past the cap.

        SELL only reduces exposure, so the cap does not apply to it.
        """
        if self.max_notional is None:
            raise RiskError(f"{CAP_ENV} is not set; refusing to trade")
        qty = self.round_qty(symbol, qty)
        if qty <= 0:
            raise RiskError(f"{symbol}: quantity rounds to zero at this step size")

        price = price or self.price(symbol)
        notional = qty * price
        floor = self.min_notional(symbol)
        if notional < floor:
            raise RiskError(f"{symbol}: {notional:.2f} is below the "
                            f"{floor:.0f} minimum for this pair")

        if side.upper() == "BUY":
            after = self.exposure(quote) + notional
            if after > self.max_notional:
                raise RiskError(f"{symbol}: would take holdings to {after:.2f} {quote}, "
                                f"over the {self.max_notional:.2f} cap")

        p = {"symbol": symbol, "side": side.upper(), "type": "MARKET", "quantity": qty}
        if client_id:
            p["newClientOrderId"] = client_id
        return self.call("/api/v1/order", "POST", **p)


def tradable_here(db_path="data.db"):
    """Symbols we collect futures signals for that can actually be bought here."""
    with urllib.request.urlopen(BASE + "/api/v1/exchangeInfo", timeout=10) as r:
        info = json.load(r)
    th = {s["symbol"] for s in info["symbols"] if s.get("status") == "TRADING"}
    signals = {row[0] for row in sqlite3.connect(db_path).execute(
        "SELECT DISTINCT symbol FROM positioning")}
    return sorted(signals & th), sorted(signals - th)


if __name__ == "__main__":
    load_env()
    if "--symbols" in sys.argv:
        both, futures_only = tradable_here()
        print(f"tradable here with a signal ({len(both)}): {', '.join(both)}")
        print(f"\nsignal but not listed here ({len(futures_only)}): {', '.join(futures_only)}")
        sys.exit(0)

    c = BinanceTH()
    print("balances:", c.balances())
    print("exposure (THB):", f"{c.exposure():.2f}")
    print("cap:", c.max_notional if c.max_notional is not None else f"{CAP_ENV} not set")
