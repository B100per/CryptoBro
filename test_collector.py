from collector import build_row, top_symbols

prem = {"symbol": "BTCUSDT", "markPrice": "80641.2", "lastFundingRate": "0.00005852"}
tick = {"symbol": "BTCUSDT", "quoteVolume": "9.0e9"}
oi = {"sumOpenInterest": "112379.323", "sumOpenInterestValue": "9064538529.79"}
ratio = {"longShortRatio": "0.9026"}
taker = {"buySellRatio": "0.8789", "buyVol": "157.574", "sellVol": "179.279"}

row = build_row(1788503700000, "BTCUSDT", prem, tick, oi, ratio, ratio, ratio, taker)
assert len(row) == 13 and row[:2] == (1788503700000, "BTCUSDT")
assert row[3] == 0.00005852 and row[5] == 112379.323 and row[10] == 0.8789

tickers = [
    {"symbol": "ETHUSDT", "quoteVolume": "5"},
    {"symbol": "BTCUSDT", "quoteVolume": "9"},
    {"symbol": "BTCUSDT_260327", "quoteVolume": "99"},  # delivery, excluded
    {"symbol": "BTCUSDC", "quoteVolume": "99"},          # not USDT, excluded
]
assert top_symbols(tickers, n=1) == ["BTCUSDT"]
assert top_symbols(tickers) == ["BTCUSDT", "ETHUSDT"]
print("ok")
