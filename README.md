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

Three agents: the collector runs continuously, paper trading rebalances hourly,
retention rolls old bars at 04:30.

```bash
for j in com.b100per.cryptobro com.b100per.cryptobro.paper com.b100per.cryptobro.retention; do
  cp $j.plist ~/Library/LaunchAgents/
  launchctl bootstrap gui/$(id -u) ~/Library/LaunchAgents/$j.plist
done
launchctl kickstart -k gui/$(id -u)/com.b100per.cryptobro   # restart after a code change
launchctl bootout gui/$(id -u)/com.b100per.cryptobro        # stop one
```

A sleeping Mac leaves gaps: the collector misses those 5m windows permanently,
and paper trading simply skips the rebalance. Neither corrupts anything.

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

API key: enable **Futures** only, never withdrawal, restrict to your IP.
Spot permission is not enough; every endpoint here is `fapi`.

The key must come from **binance.com** or its futures testnet. Binance TH
(`binance.th`) is a separate exchange whose keys are rejected here, and it has
no futures market at all, so the funding / open interest / long-short signals
this bot is built on do not exist on that account.

Credentials live in `.env`, which is gitignored:

```bash
cp .env.example .env    # then fill it in
python3 binance_client.py            # testnet unless BINANCE_LIVE=1
python3 binance_client.py --diagnose # which environment does this key belong to?
```

An `export` in the shell, or systemd's `EnvironmentFile`, still overrides the
file. On the VPS use `/etc/cryptobro.env` (root-only) rather than a repo file.

## Binance TH (spot)

`binance_th.py` executes on the Thai account. It is a different exchange from
binance.com: host `api.binance.th`, `/api/v1` paths, and **spot only**. No
futures means no funding, no open interest, no long/short ratio, and **no way
to short**. Signals still come from binance.com futures data, which the
collector reads without a key; only execution happens here.

```bash
python3 binance_th.py            # balances, current exposure, cap
python3 binance_th.py --symbols  # pairs listed here that we have signals for
```

`MAX_NOTIONAL_THB` caps holdings in baht. SELL is never blocked by the cap,
since exiting can only reduce exposure. Minimum order is 100 THB on every THB
pair, and about 5 USDT on the USDT pairs.

## Dry run

```bash
python3 trade.py                 # plan against THB pairs, sends nothing
python3 trade.py --quote USDT    # plan against USDT pairs (21 candidates)
python3 trade.py --live          # send, after typing a confirmation phrase
```

Equal weight across the top-scoring coins, capped by whichever is smaller:
`MAX_NOTIONAL_<quote>` or what is actually free in the account. Position count
is set by the exchange minimum, not by preference: at a 100 THB floor, a 1000
THB budget is ten slots and no more. Coins already held that still rank are
left alone; ones that no longer rank are sold, unless the holding is dust
below the pair minimum.

## Backtest

```bash
python3 collector.py --history 90   # page back 90 days of 5m candles first
python3 backtest.py                 # walk-forward, all symbols
python3 backtest.py --th --top 3 --rebalance 288 --fee 0.001
```

Rebalances a portfolio into the top scorers exactly the way `trade.py` does,
so the number answers the question that matters. Scores are price-only:
Binance serves 30 days of positioning data and the collector started
2026-09-04, so those terms cannot be backtested yet.

**Result on 90 days, 59 symbols, 0.1% fee, hourly rebalance: -91%.** At zero
fees the same run is -8.9%, so the signal has no edge to lose in the first
place; fees then turn flat into ruin. Do not run this live.

## Alerts and journal

```bash
python3 notify.py "test"     # Discord webhook, DISCORD_WEBHOOK_URL in .env
python3 journal.py           # totals
python3 journal.py --tail 20 # recent entries
```

Every planned and executed order is appended to `logs/trades.csv` and
`logs/trades.json`. Alerts are best-effort: a dead webhook logs and moves on
rather than taking the trading loop down.

## Regime

`regime.py` decides whether a market is worth acting in at all. Trend
following pays in a trend and bleeds in chop, and the 90-day backtest made
5,533 trades to lose 91%, which is what that bleeding looks like.

Efficiency ratio (Kaufman) is distance travelled over ground covered: a clean
one-way move approaches 1, a market that thrashes and ends where it began
approaches 0. Below `TREND_MIN`, or with ATR in the top of its own range, the
score is forced below anything the planner will buy.

```bash
python3 features.py --th    # scores with the regime column
```

## Paper trading

```bash
python3 paper.py --step      # one rebalance, run on a schedule
python3 paper.py --status    # equity, drawdown, open positions
python3 paper.py --reset
```

Same rule, real prices, imaginary money, and prices the rule has never seen.
State is in `paper.db`, kept apart from `data.db` so a long collector backfill
can never block it.

## Retention

5m bars for 384 pairs is ~140k rows a day, roughly 3 GB a year. Nobody needs
five-minute resolution from eight months ago, so old bars are rolled into 1h,
which is 12x smaller and answers the same long-horizon question.

```bash
python3 retention.py --dry-run   # what would be rolled
python3 retention.py --days 45   # roll, delete, VACUUM
```

Runs daily on the VPS via `retention.timer`. Backtests past the 5m window read
the rolled tables: `python3 backtest.py --table th_klines_1h`.

## Circuit breaker

`risk.py` halts buying for the rest of the UTC day once account equity drops
`DAILY_DRAWDOWN_LIMIT` from where it started the day. Selling is never blocked.
The trip is sticky, and the day's anchor is written to `risk_state.json` so a
restart does not forget it.

```bash
python3 risk.py    # today's anchor, drawdown and trip state
```

Ported from the Alpaca bot in `../Trading_bot`, minus the equities-specific
parts: PDT limits, end-of-day flush and market hours do not apply to crypto.

## Risk cap

`MAX_NOTIONAL_USDT` is a hard ceiling on gross position notional. With no value
set, `order()` refuses to send anything. Every order is also checked against the
symbol's own `LOT_SIZE` and `MIN_NOTIONAL` filters before it leaves the machine.

The cap is the second line of defence. The first is the futures wallet balance:
transfer in only what you are willing to lose, because nothing in this repo can
lose more than what is in that wallet.

Minimum order size is set by Binance, not by this code:

| symbol | min notional |
|---|---|
| BTCUSDT | 50 USDT |
| ETHUSDT | 20 USDT |
| most alts | 5 USDT |

`close_all()` is the kill switch and flattens every open position at market.

## Tests

```bash
python3 test_collector.py && python3 test_features.py && python3 test_binance_client.py
```

## Roadmap

Collect -> walk-forward backtest -> paper trade on testnet -> live at 1-2x leverage.
Risk sizing, kill switch and execution reconciliation are not written yet.
