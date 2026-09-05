"""Signed Binance USDT-M futures client. Testnet by default.

Setup:
  1. Binance -> API Management -> create key. Enable "Futures" ONLY.
     Never enable withdrawal. Restrict to your IP.
  2. Testnet keys instead: https://testnet.binancefuture.com
  3. export BINANCE_KEY=... BINANCE_SECRET=...
     Production also needs: export BINANCE_LIVE=1

  python3 binance_client.py    # prints balance + open positions

Every private call is HMAC-SHA256 signed over the query string and sent with
an X-MBX-APIKEY header. That signing is the whole of "connecting your account".
"""
import hashlib
import hmac
import json
import math
import os
import sys
import time
import urllib.parse
import urllib.request

TESTNET = "https://testnet.binancefuture.com"
LIVE = "https://fapi.binance.com"
ENV_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env")


def load_env(path=ENV_FILE):
    """Read KEY=value lines into os.environ. Already-set variables win, so an
    explicit `export` or a systemd EnvironmentFile still overrides the file."""
    try:
        with open(path) as f:
            lines = f.readlines()
    except FileNotFoundError:
        return
    for line in lines:
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        os.environ.setdefault(k.strip(), v.strip().strip("'\""))

HINTS = {
    -2015: "key is not accepted here. Common causes, in the order worth checking: "
           "the key is from a different Binance entity (a binance.th / Binance TH key "
           "does not work on binance.com, and Binance TH has no futures at all); the "
           "key is for the other environment (testnet keys only work on testnet); "
           "Futures is not enabled on the key; your IP is not whitelisted. "
           "Run `python3 binance_client.py --diagnose` to narrow it down",
    -2014: "malformed API key: check for a stray space or newline in BINANCE_KEY",
    -1022: "signature rejected: BINANCE_SECRET does not match BINANCE_KEY",
    -1021: "your system clock is off; sync it and retry",
}


def get_public(url):
    with urllib.request.urlopen(url, timeout=10) as r:
        return json.load(r)


class RiskError(Exception):
    """Refused locally, before anything reached the exchange."""


class BinanceError(Exception):
    def __init__(self, status, body, path):
        try:
            code = json.loads(body).get("code")
            msg = json.loads(body).get("msg", body)
        except ValueError:
            code, msg = None, body
        hint = HINTS.get(code)
        super().__init__(f"{path} -> HTTP {status} code={code} {msg}"
                         + (f"\n  hint: {hint}" if hint else ""))
        self.status, self.code = status, code


class Binance:
    def __init__(self, key=None, secret=None, live=None, max_notional=None):
        if not (key and secret):
            load_env()
        self.key = key or os.environ["BINANCE_KEY"]
        self.secret = (secret or os.environ["BINANCE_SECRET"]).encode()
        # ponytail: live trading needs a deliberate flag, never a default
        self.live = os.environ.get("BINANCE_LIVE") == "1" if live is None else live
        self.base = LIVE if self.live else TESTNET
        # Hard ceiling on gross notional. No default: trading without one is refused.
        cap = os.environ.get("MAX_NOTIONAL_USDT") if max_notional is None else max_notional
        self.max_notional = float(cap) if cap not in (None, "") else None
        self._filters = None

    def sign(self, params):
        qs = urllib.parse.urlencode(params)
        return qs + "&signature=" + hmac.new(self.secret, qs.encode(), hashlib.sha256).hexdigest()

    def call(self, path, method="GET", base=None, **params):
        params.setdefault("timestamp", int(time.time() * 1000))
        params.setdefault("recvWindow", 5000)
        qs = self.sign(params)
        url = f"{base or self.base}{path}" + ("?" + qs if method == "GET" else "")
        req = urllib.request.Request(
            url, data=None if method == "GET" else qs.encode(),
            headers={"X-MBX-APIKEY": self.key}, method=method)
        try:
            with urllib.request.urlopen(req, timeout=10) as r:
                return json.load(r)
        except urllib.error.HTTPError as e:
            # Binance puts the real reason in the body; without this every failure
            # is an opaque "HTTP Error 401" and you cannot tell key from IP from clock.
            raise BinanceError(e.code, e.read().decode(errors="replace"), path) from None

    def balance(self):
        return [b for b in self.call("/fapi/v2/balance") if float(b["balance"]) > 0]

    def positions(self):
        """Source of truth for what you actually hold. Never trust in-memory state."""
        return [p for p in self.call("/fapi/v2/positionRisk") if float(p["positionAmt"]) != 0]

    def set_leverage(self, symbol, leverage):
        return self.call("/fapi/v1/leverage", "POST", symbol=symbol, leverage=leverage)

    def filters(self, symbol):
        """Per-symbol LOT_SIZE / MIN_NOTIONAL rules. Fetched once, then cached."""
        if self._filters is None:
            info = get_public(self.base + "/fapi/v1/exchangeInfo")
            self._filters = {s["symbol"]: {f["filterType"]: f for f in s["filters"]}
                             for s in info["symbols"]}
        return self._filters[symbol]

    def round_qty(self, symbol, qty):
        """Down to the symbol's step size. Rounding up could push past the cap."""
        step = float(self.filters(symbol)["LOT_SIZE"]["stepSize"])
        return math.floor(qty / step) * step

    def exposure(self):
        """Gross notional currently at risk, in USDT."""
        return sum(abs(float(p["positionAmt"]) * float(p["markPrice"]))
                   for p in self.positions())

    def order(self, symbol, side, qty, client_id=None, price=None):
        """Market order, refused if it would push gross exposure past max_notional.

        client_id makes a retry after a network timeout a no-op instead of a
        second position.
        """
        if self.max_notional is None:
            raise RiskError("MAX_NOTIONAL_USDT is not set; refusing to trade")
        qty = self.round_qty(symbol, qty)
        if qty <= 0:
            raise RiskError(f"{symbol}: quantity rounds to zero at this step size")

        price = price or float(get_public(
            self.base + f"/fapi/v1/ticker/price?symbol={symbol}")["price"])
        notional = qty * price
        min_notional = float(self.filters(symbol)["MIN_NOTIONAL"]["notional"])
        if notional < min_notional:
            raise RiskError(f"{symbol}: {notional:.2f} USDT is below the "
                            f"{min_notional:.0f} USDT minimum for this symbol")

        after = self.exposure() + notional
        if after > self.max_notional:
            raise RiskError(f"{symbol}: would take gross exposure to {after:.2f} USDT, "
                            f"over the {self.max_notional:.2f} USDT cap")

        p = {"symbol": symbol, "side": side, "type": "MARKET", "quantity": qty}
        if client_id:
            p["newClientOrderId"] = client_id
        return self.call("/fapi/v1/order", "POST", **p)

    def close_all(self):
        """Kill switch. Flattens every open position at market."""
        out = []
        for pos in self.positions():
            amt = float(pos["positionAmt"])
            out.append(self.call("/fapi/v1/order", "POST", symbol=pos["symbol"],
                                 side="SELL" if amt > 0 else "BUY", type="MARKET",
                                 quantity=abs(amt), reduceOnly="true"))
        return out


def diagnose():
    """Which environment does this key actually belong to? Tries both and reports."""
    load_env()
    key, secret = os.environ.get("BINANCE_KEY", ""), os.environ.get("BINANCE_SECRET", "")
    print(f"key length {len(key)}, secret length {len(secret)} (Binance issues 64 chars each)")
    if key != key.strip() or secret != secret.strip():
        print("  !! whitespace around the key or secret; strip it")
    # Spot reading is the weakest permission there is. If even that is refused,
    # the key is not a binance.com key at all rather than missing a permission.
    try:
        Binance(key, secret, live=True).call("/api/v3/account",
                                             base="https://api.binance.com")
        print("SPOT   : OK  <- key is valid on binance.com")
    except BinanceError as e:
        if e.code == -2015:
            print("SPOT   : refused -> this key is not recognised by binance.com. "
                  "Check it is not a binance.th (Binance TH) key, which is a separate "
                  "exchange with no futures.")
        else:
            print(f"SPOT   : code={e.code}")
    except Exception as e:
        print(f"SPOT   : {e}")
    for live in (False, True):
        name = "LIVE   " if live else "TESTNET"
        try:
            Binance(key, secret, live=live).call("/fapi/v2/balance")
            print(f"{name}: OK  <- this key belongs here")
        except BinanceError as e:
            print(f"{name}: code={e.code} {e}".split("\n")[0])
        except Exception as e:
            print(f"{name}: {e}")


if __name__ == "__main__":
    if "--diagnose" in sys.argv:
        diagnose()
        sys.exit(0)
    b = Binance()
    env = "LIVE" if b.live else "TESTNET"
    print(env, b.base)
    try:
        print("balance:", b.balance())
        print("positions:", b.positions())
    except BinanceError as e:
        print(f"FAILED: {e}")
        other = "live" if not b.live else "testnet"
        print(f"  note: this key must be one you created on {env.lower()}. "
              f"Keys from {other} are rejected here.")
        sys.exit(1)
