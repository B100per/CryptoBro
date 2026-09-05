from binance_th import BinanceTH
from trade import plan

PRICES = {"BTCTHB": 2_700_000.0, "ETHTHB": 84_000.0, "SOLTHB": 3_400.0,
          "XRPTHB": 60.0, "BNBTHB": 30_000.0}

def stub(cap, holdings, scores):
    c = BinanceTH(key="k", secret="s", max_notional=cap)
    c._filters = {p: {"LOT_SIZE": {"stepSize": "0.00000001"},
                      "NOTIONAL": {"minNotional": "100"}} for p in PRICES}
    c.price = lambda p: PRICES[p]
    c.balances = lambda: dict(holdings)
    import trade
    trade.candidates = lambda quote, filters, db_path=None: [
        (b + quote, b, s) for b, s in scores]
    return c

# 1000 THB at a 100 THB minimum is ten slots, but only what scores well is bought
rows, ranked, slots = plan(stub(1000, {"THB": 1000}, [("BTC", 2.0), ("ETH", 1.0)]))
assert slots == 10
assert [r[0] for r in rows] == ["BUY", "BUY"]
assert abs(sum(r[3] for r in rows) - 1000) < 1        # the whole cap is deployed, not more
assert all(r[3] >= 100 for r in rows)                 # every order clears the minimum

# something held that no longer ranks gets sold
rows, _, _ = plan(stub(1000, {"THB": 500, "SOL": 0.5}, [("BTC", 2.0)]))
assert ("SELL", "SOLTHB") == rows[0][:2]

# something held that still ranks is left alone, not re-bought
rows, _, _ = plan(stub(1000, {"THB": 500, "BTC": 0.0001}, [("BTC", 2.0)]))
assert rows == []

# dust below the pair minimum is not worth a sell order
rows, _, _ = plan(stub(1000, {"THB": 500, "SOL": 0.0001}, [("BTC", 2.0)]))
assert [r[0] for r in rows] == ["BUY"]

# a cap under one minimum order buys nothing rather than sending an undersized order
rows, _, slots = plan(stub(50, {"THB": 50}, [("BTC", 2.0)]))
assert slots == 0 and rows == []
print("ok")
