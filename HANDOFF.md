# CryptoBro — handoff

Written 2026-09-05 16:30 (Asia/Bangkok) for continuing on another machine.
Everything below is in git except where it says **not in git**.

## What this is

A long-only spot bot for Binance TH (`api.binance.th`), Python 3.9 stdlib only.
It scores every USDT pair on the board, buys the top 5, rebalances on a schedule.
**No real money has ever been traded.** All results are backtest or paper.

## State of the research

**No real money has ever been traded.** Everything below is paper or backtest.
Decision rule agreed with the owner: real money only when worst-case
out-of-sample excess over buy-and-hold is > 0 **and** 30 days of paper match.

### Paper, 5 Sep -> 28 Sep 2026 (23 days, raw returns)

| book | this PC | cloud | board, same window |
|---|---|---|---|
| chart + breadth 60% | +30.9%, maxDD 5.5% | +17.3% | median coin +16.8%, mean +25.2% |
| vol-scaled momentum | +9.5%, maxDD 30.6% | -2.9%, maxDD 38.1% | BTC +5.0%, ETH +9.4% |

Two things this says, both uncomfortable:

**Timing luck is as large as the edge.** The same rule, rebalanced a few hours
apart, is 12-13 points apart on both books. Any single number from either book
is mostly a draw from that spread.

**The chart book's +30.9% is three coins.** Realised P/L: ZAMA +148, JST +50,
PROVE +42, STRK +32, everything else under 20. It was invested 39% of the time
and bought on 5 of its 8 rebalances. A backtest of the same rule over the same
23 days returns +0.5% raw against +18.6% buy-and-hold (lab_pos.out). The live
result sits far outside the spread of five start times, and nothing in the code
explains it: the positioning input, the one real difference between the live
rule and the backtested one, moves the median not at all (see below). Until
that gap is explained, the chart book's number is not evidence of an edge.

### What the labs say now (108 days of 5-minute bars, restored 29 Sep)

- `lab_stop_108d.out` vs `lab_stop.out` (90 days): **the stop level is noise.**
  5% went +11.9 -> -10.2 worst-case, 10% went -14.2 -> +30.1, purely from adding
  18 days. We chose 15% because it led on 90 days; on 108 days 20% leads. Left
  at 15% because no level is defensibly better, not because 15% won.
- Stable across both datasets: volmom's worst case is positive at nearly every
  stop level; chart's is negative at every one, and on 108 days even its best
  start time loses to buy-and-hold.
- `lab_chase.out`, `lab_chase_wide.out`: **refusing to chase a spike: measured,
  rejected.** A 100%/1-day cap is a clean peak (worst +19.7 -> +57.3, median
  +99.3 -> +147.2, decaying back to baseline by 300%). It would also have
  blocked **0 of the 51 buys the live book actually made**. IOST, the trade that
  prompted the idea, was -18% on the day this PC bought it; MUBARAK, the worst
  trade at -72 USDT, was +85%, just under the cap. A gate that changes nothing
  live and everything in backtest is a curve fit. Not shipped.
- `lab_pos.out`: **the live chart rule is not the backtested one, and it does
  not matter.** backtest.chart_signal scores `score(chart, None)`; features.load,
  which paper.py and the cloud run, scores `score(chart, pos)` - funding, OI
  change, smart-money/retail split, for the 78 of 385 symbols the futures
  collector covers. Measured over the 23 days positioning exists: identical
  worst and median, best case -9.1 -> -6.2. The difference HANDOFF had been
  waiting to test since September is real but too small to matter.

### Reading the lab tables

Every column except `raw%` and `hold%` is **excess over buy-and-hold**. Reading
an excess figure against a live book's raw return is how the chart book looked
impossible for a day; lab_pos.py prints both for exactly that reason.

## What is running, and where

Moved to the Windows PC (F:\CryptoBro) on 2026-09-05. Three scheduled tasks,
registered by `deploy\windows\install.ps1`, run from logon with no window
(user tasks: a reboot nobody logs in after runs nothing, same as launchd was):

| task | does | log |
|---|---|---|
| `CryptoBro collector` | `collector.py` forever, restarted a minute after any exit; on start it refills every hole in the last week of TH bars, at the end or in the middle (`heal`, one page a symbol for a 12 h outage) | `logs\collector.log` |
| `CryptoBro retention` | `retention.py --days 45` daily 04:30 | `logs
etention.log` |
| `CryptoBro control` | `control.py` on `127.0.0.1:8787`, token lifted from `.env`; rebalance 36 h, mark + stop-loss every 5 min | `logs\control.log` |

`Get-ScheduledTask "CryptoBro *"` shows them; `Start-/Stop-ScheduledTask` drives them.
`data.db` was rebuilt here with `collector.py --history 90` (TH klines 90 days;
positioning starts from 2026-09-05 because Binance keeps 30 days and the
Mac's collected history was not copied). The paper books start fresh unless
`paper_chart.db`, `paper_volmom.db`, `control_state.json` are copied from the Mac.

The Mac's launchd agents should be unloaded so it stops collecting too:
`launchctl bootout gui/$(id -u)/com.b100per.cryptobro` and the same for
`.retention`. The cloud books (Firebase, below) run regardless of any machine.

## To resume on the new machine

```bash
git clone https://github.com/B100per/CryptoBro.git && cd CryptoBro
cp /path/from/old/mac/.env .          # or recreate, see below — never commit it
# Windows instead of the last two lines: powershell -ExecutionPolicy Bypass -File deploy\windows\install.ps1
for f in test_*.py signals.py book.py cloud/functions/test_step.py; do python3 $f; done  # all print ok
python3 collector.py --once           # small data.db to start with
CONTROL_TOKEN=$(grep CONTROL_TOKEN .env | cut -d= -f2) python3 control.py
open http://127.0.0.1:8787
```

`.env` keys (**never in git**, never in chat): `BINANCE_KEY`, `BINANCE_SECRET`
(binance.th key, spot only, **no withdrawal**, IP-restricted), `DISCORD_WEBHOOK`,
`CONTROL_TOKEN` (any long random string), `MAX_NOTIONAL_THB=1000`.

A full 90-day backfill (`collector.py --history 90`) takes ~1 h 20 and 1.2 GB.
The backtests need it; the paper books do not (they read the last ~2016 bars).

## Firebase (deployed 2026-09-05, https://cryptobro-591d7.web.app)

Project: `cryptobro-591d7`. Hosting serves the panel, a scheduled Python Cloud
Function runs the step every 12 h fetching klines live from binance.th,
Firestore holds the books, rules restrict everything to one Google account.

- `cloud/functions/step.py`: the step, no Firebase in it. Same ranking as
  `paper.py` (liquidity, breadth, chart, volmom) over bars held in memory;
  arithmetic from `book.py`. `test_step.py` runs it with a fake exchange.
- `cloud/functions/main.py`: `paper_step` (Cloud Scheduler, every 36 h, only
  while `control/state.running`), `paper_watch` (every 5 min: one price call,
  a mark on each book, the stop-loss) and `step_now` (callable, owner only).
- `cloud/public/index.html`: Google sign-in, live books from Firestore,
  Start / Stop / Run one step now. Loads the SDK from Hosting's reserved
  `/__/firebase/` URLs, so no config is pasted in; it only works served by
  Firebase Hosting (or `firebase serve`), not from a file.
- Firestore: `control/state` {running, last_step, stepping}; `books/{chart,volmom}`
  {cash, held, marks (live prices), curve (rebalance points), watch (5-min marks, a week),
  equity, return_pct, ...}; `books/*/fills/*` (side BUY/SELL/STOP).

One known difference: the local chart book adds the positioning terms for
the ~20 symbols the futures collector covers (`features.load` reads the
positioning table); the backtest and the cloud book score price only, which
is what the lab measured. Compare the two books with that in mind.

Deployed once from this Windows machine: Blaze is on, the Web app is
registered, `OWNER_EMAIL` is in `cloud/firestore.rules` and in the gitignored
`cloud/functions/.env`, the runtime is python311 (what was installed), and the
Artifact Registry cleanup policy is set (images older than a day are deleted).
Still to do in the console, once: Authentication → Sign-in method → enable
Google. Until then the page's sign-in button fails.

Redeploy is `cd cloud && functions/build.sh && firebase deploy --non-interactive`.
The books start at 1000 USDT in the cloud; the local sqlite books are not migrated.
Research (backtests, lab) stays local: it needs the 1.2 GB database.

## Conventions

- New feature → new branch → tests → `merge --no-ff` to main → push main AND the
  branch. **Never delete a branch after merging** (owner's rule). Bug fixes on main.
- Every non-trivial module has a `test_*.py` or `demo()`; run them before pushing.
- Measure any strategy change with `python3 lab.py` / `backtest.py --robust`:
  report the **worst** start time as excess over buy-and-hold, never the best.
- `paper.py` and `control.py` must never import the exchange client; `test_control.py` asserts it.
- Live trading is only `trade.py --live` (chart rule) or `live.py --live` (momentum
  rule, the one that passed); both demand typing `yes i am sure`. `live.py --watch --live`
  is the 15 % stop-loss for the real account: it only ever sells, asks nothing, and is
  meant for a 5-minute schedule. The `.env` key must be a **binance.th** key; the one
  there on 2026-09-09 was refused (-2015), so nothing can be sent until that is fixed.

## Files

| file | role |
|---|---|
| `collector.py` | data → `data.db` (WAL) |
| `features.py`, `regime.py` | chart signal + per-coin regime gate |
| `signals.py` | alternative rules (momentum, volmom, reversal, breakout, surge, trend_broken) |
| `book.py` | pure rebalance arithmetic shared by paper and cloud |
| `backtest.py` | walk-forward portfolio backtest; `--robust`, `--take-profit` lives on branch `feature/take-profit` (unmerged, no effect measured) |
| `lab.py` | signal comparison, worst case across start times |
| `paper.py` | forward test into sqlite; `--rule chart|volmom --breadth --min-vol` |
| `control.py` | web panel + scheduler for both paper books |
| `dashboard.py`, `progress.py` | self-refreshing HTML views |
| `trade.py`, `live.py`, `binance_th.py`, `binance_client.py`, `risk.py` | the only path to real orders; `live.py` keeps entries in `live_volmom.db` |
| `cloud/` | Firebase: `functions/step.py` + `main.py` (the 12 h step), `public/index.html` (the panel) |
| `deploy/` | systemd units + `install.sh` for a VPS; `deploy/windows/` scheduled tasks + `install.ps1` for a PC |
| `lab_*.out` | measured results, see above |
| `lab_chase.py` | does refusing to chase a spike help? measured, rejected |
| `lab_pos.py` | is the live chart rule (with positioning) better than the backtested one? no |
