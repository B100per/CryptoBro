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
