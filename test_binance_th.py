from binance_client import RiskError
from binance_th import BinanceTH

def stub(cap, holdings_thb, step="0.01", min_notional=100.0):
    c = BinanceTH(key="k", secret="s", max_notional=cap)
    c._filters = {"SOLTHB": {"LOT_SIZE": {"stepSize": step},
                             "NOTIONAL": {"minNotional": str(min_notional)}}}
    c.exposure = lambda quote="THB": holdings_thb
    c.price = lambda s: 3400.0
    c.call = lambda *a, **k: {"placed": k}
    return c

def buy(c, qty):
    try:
        c.order("SOLTHB", "BUY", qty)
        return None
    except RiskError as e:
        return str(e)

assert BinanceTH(key="k", secret="s").base == "https://api.binance.th"

# no cap set -> nothing is sent
assert "MAX_NOTIONAL_THB is not set" in buy(stub(None, 0), 1.0)

# 3400 THB of SOL against a 1000 THB cap is refused
assert "over the 1000.00 cap" in buy(stub(1000, 0), 1.0)

# the cap counts what is already held, not just this order
assert "over the 1000.00 cap" in buy(stub(1000, 900), 0.05)

# below the pair's 100 THB minimum is refused locally
assert "below the 100 minimum" in buy(stub(5000, 0), 0.02)

# rounds down to the step size, never up past the cap
c = stub(5000, 0, step="0.01")
assert buy(c, 0.119) is None
assert c.round_qty("SOLTHB", 0.119) == 0.11

# SELL reduces exposure, so the cap must not block an exit
c = stub(100, 100000)
c.order("SOLTHB", "SELL", 1.0)
print("ok")
