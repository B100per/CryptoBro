# CryptoBro

Binance USDT-M futures positioning bot. Step 1: collect data (Binance only keeps 30 days, so collect before strategising).

```bash
python3 collector.py          # every 5 min -> data.db (sqlite)
python3 collector.py --once   # single cycle
python3 test_collector.py     # offline check
```

Table `positioning` (ts, symbol): mark_price, funding, quote_vol_24h, oi, oi_value,
top_acct, top_pos, global_acct (long/short ratios), taker_ratio, taker_buy, taker_sell.

Roadmap: collector -> feature engine -> scoring -> risk/sizing -> execution (testnet first).
