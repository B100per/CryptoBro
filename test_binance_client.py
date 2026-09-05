from binance_client import Binance, LIVE, TESTNET

# Signature vector from the Binance API docs.
b = Binance(key="x", secret="NhqPtmdSJYdKjVHjA7PZj4Mge3R5YNiP1e3UZjInClVN65XAbvqqM6A7H5fATj0j",
            live=False)
qs = b.sign({"symbol": "LTCBTC", "side": "BUY", "type": "LIMIT", "timeInForce": "GTC",
             "quantity": 1, "price": "0.1", "recvWindow": 5000, "timestamp": 1499827319559})
assert qs.endswith("&signature=c8db56825ae71d6d79447849e617115f4a920fa2acdcab2b053c4b2838bd6b71"), qs

assert Binance(key="x", secret="y", live=False).base == TESTNET
assert Binance(key="x", secret="y", live=True).base == LIVE
print("ok")

from binance_client import BinanceError

e = BinanceError(401, '{"code":-2015,"msg":"Invalid API-key, IP, or permissions for action."}', "/fapi/v2/balance")
assert e.code == -2015 and e.status == 401
assert "wrong environment" in str(e)          # the hint has to reach the user

plain = BinanceError(502, "<html>bad gateway</html>", "/fapi/v1/order")
assert plain.code is None and "bad gateway" in str(plain)   # non-JSON body must not crash
print("ok")

import os, tempfile
from binance_client import load_env

with tempfile.NamedTemporaryFile("w", suffix=".env", delete=False) as f:
    f.write('# comment\n\nBINANCE_KEY=abc123\nBINANCE_SECRET="quoted secret"\n'
            'SPACED = padded \nMALFORMED\nPRESET=fromfile\n')
    path = f.name

os.environ.pop("BINANCE_KEY", None)
os.environ["PRESET"] = "fromshell"
load_env(path)
assert os.environ["BINANCE_KEY"] == "abc123"
assert os.environ["BINANCE_SECRET"] == "quoted secret"   # quotes stripped
assert os.environ["SPACED"] == "padded"                  # whitespace stripped both sides
assert "MALFORMED" not in os.environ                     # no "=" means skip, not crash
assert os.environ["PRESET"] == "fromshell"               # shell must win over the file
load_env("/nonexistent/.env")                            # missing file is not an error
os.unlink(path)
print("ok")

from binance_client import RiskError

def stub(cap, exposure_usdt, step="0.001", min_notional="50"):
    """A client that never touches the network, so the guards can be tested offline."""
    c = Binance(key="k", secret="s", live=False, max_notional=cap)
    c._filters = {"BTCUSDT": {"LOT_SIZE": {"stepSize": step},
                              "MIN_NOTIONAL": {"notional": min_notional}}}
    c.exposure = lambda: exposure_usdt
    c.call = lambda *a, **k: {"placed": k}
    return c

def attempt(c, qty, price=100000.0):
    try:
        c.order("BTCUSDT", "BUY", qty, price=price)
        return None
    except RiskError as e:
        return str(e)

# no cap configured -> nothing may be sent, even a tiny order
assert "MAX_NOTIONAL_USDT is not set" in attempt(stub(None, 0), 0.001)

# a 100 USDT order against a 30 USDT cap must be refused
assert "over the 30.00 USDT cap" in attempt(stub(30, 0), 0.001)

# the cap counts positions already open, not just this order
assert "over the 60.00 USDT cap" in attempt(stub(60, 55), 0.001)

# below the symbol's minimum notional is refused before it reaches Binance
assert "below the 50 USDT minimum" in attempt(stub(1000, 0, min_notional="50"), 0.001, price=10000.0)

# quantity that rounds down to nothing must not be sent as zero
assert "rounds to zero" in attempt(stub(1000, 0, step="0.01"), 0.004)

# a legal order inside the cap goes through, rounded down to the step size
c = stub(1000, 0, step="0.001", min_notional="5")
assert attempt(c, 0.0019) is None
assert c.round_qty("BTCUSDT", 0.0019) == 0.001    # floored, never rounded up past the cap
print("ok")
