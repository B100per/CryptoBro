# CryptoBro

Binance USDT-M futures positioning bot.

Binance only serves 30 days of positioning history, so data collection has to run
before any strategy work can be backtested. Price candles have full history and
are backfilled on demand.

## Collect

```bash
python3 collector.py --backfill   # one cycle + ~3.5 days of 5m candles
python3 collector.py              # every 5 min -> data.db
```

### 24/7 on a VPS (preferred)

A laptop that sleeps leaves gaps in the data. On a Debian/Ubuntu box, as root:

```bash
curl -fsSL https://raw.githubusercontent.com/B100per/CryptoBro/main/deploy/install.sh | bash
```

Installs to `/opt/cryptobro` as a system user, backfills, then enables the
`cryptobro` systemd unit. Re-run it to deploy a new commit. Logs go to journald:

```bash
journalctl -u cryptobro -f
```

### 24/7 on macOS (launchd)

```bash
cp com.b100per.cryptobro.plist ~/Library/LaunchAgents/
launchctl bootstrap gui/$(id -u) ~/Library/LaunchAgents/com.b100per.cryptobro.plist
launchctl kickstart -k gui/$(id -u)/com.b100per.cryptobro   # restart after a code change
launchctl bootout gui/$(id -u)/com.b100per.cryptobro        # stop, once the VPS is collecting
```

Tables, both keyed on (ts, symbol) for the top 50 perpetuals by 24h volume:

- `positioning` — mark_price, funding, quote_vol_24h, oi, oi_value, top_acct,
  top_pos, global_acct, taker_ratio, taker_buy, taker_sell
- `klines` — 5m open, high, low, close, volume, quote_vol, trades, taker_buy_base

## Read the chart

```bash
python3 features.py          # ranked table
python3 features.py --json
```

Trend from EMA spread over ATR, market structure from higher-high/higher-low,
minus crowding from funding and the top-trader vs retail divergence. Positioning
terms stay near zero until the collector has a few hours of history.

## Account

```bash
export BINANCE_KEY=... BINANCE_SECRET=...
python3 binance_client.py    # testnet unless BINANCE_LIVE=1
```

API key: enable Futures only, never withdrawal, restrict to your IP.

## Tests

```bash
python3 test_collector.py && python3 test_features.py && python3 test_binance_client.py
```

## Roadmap

Collect -> walk-forward backtest -> paper trade on testnet -> live at 1-2x leverage.
Risk sizing, kill switch and execution reconciliation are not written yet.
