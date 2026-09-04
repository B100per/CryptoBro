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
import os
import time
import urllib.parse
import urllib.request

TESTNET = "https://testnet.binancefuture.com"
LIVE = "https://fapi.binance.com"


class Binance:
    def __init__(self, key=None, secret=None, live=None):
        self.key = key or os.environ["BINANCE_KEY"]
        self.secret = (secret or os.environ["BINANCE_SECRET"]).encode()
        # ponytail: live trading needs a deliberate flag, never a default
        self.live = os.environ.get("BINANCE_LIVE") == "1" if live is None else live
        self.base = LIVE if self.live else TESTNET

    def sign(self, params):
        qs = urllib.parse.urlencode(params)
        return qs + "&signature=" + hmac.new(self.secret, qs.encode(), hashlib.sha256).hexdigest()

    def call(self, path, method="GET", **params):
        params.setdefault("timestamp", int(time.time() * 1000))
        params.setdefault("recvWindow", 5000)
        qs = self.sign(params)
        url = f"{self.base}{path}" + ("?" + qs if method == "GET" else "")
        req = urllib.request.Request(
            url, data=None if method == "GET" else qs.encode(),
            headers={"X-MBX-APIKEY": self.key}, method=method)
        with urllib.request.urlopen(req, timeout=10) as r:
            return json.load(r)

    def balance(self):
        return [b for b in self.call("/fapi/v2/balance") if float(b["balance"]) > 0]

    def positions(self):
        """Source of truth for what you actually hold. Never trust in-memory state."""
        return [p for p in self.call("/fapi/v2/positionRisk") if float(p["positionAmt"]) != 0]

    def set_leverage(self, symbol, leverage):
        return self.call("/fapi/v1/leverage", "POST", symbol=symbol, leverage=leverage)

    def order(self, symbol, side, qty, client_id=None):
        """Market order. client_id makes a retry after a network timeout a no-op
        instead of a second position."""
        p = {"symbol": symbol, "side": side, "type": "MARKET", "quantity": qty}
        if client_id:
            p["newClientOrderId"] = client_id
        return self.call("/fapi/v1/order", "POST", **p)


if __name__ == "__main__":
    b = Binance()
    print("LIVE" if b.live else "TESTNET", b.base)
    print("balance:", b.balance())
    print("positions:", b.positions())
