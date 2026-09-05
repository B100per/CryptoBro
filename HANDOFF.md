# CryptoBro — handoff

Written 2026-09-05 16:30 (Asia/Bangkok) for continuing on another machine.
Everything below is in git except where it says **not in git**.

## What this is

A long-only spot bot for Binance TH (`api.binance.th`), Python 3.9 stdlib only.
It scores every USDT pair on the board, buys the top 5, rebalances on a schedule.
**No real money has ever been traded.** All results are backtest or paper.

## State of the research (read this first)

- The original chart-reading signal (`features.py`) has **no demonstrated edge**.
  Its backtest return depends on which hour you start: same rule, same data,
  -33.6 % to +86.7 % from a few hours' shift. See `lab_base.out`.
- Fees dominate. Rebalancing hourly loses ~97 % in 90 days from fees alone.
- **Cadence matters more than anything else measured.** Both surviving rules
  FAIL the worst-case test at 12 h and pass only at 36 h (`lab.out`: volmom
  -55 % vs +4.6 %; chart -40 % vs +23 %). The paper books and the cloud ran at
  12 h until 2026-09-05 by mistake; both now rebalance every **36 h**.
- On the 90 days ending 2026-09-05 (`lab_stop.out`, 36 h, ≥ 2,000 USDT/5 min,
  5 start times, excess over buy-and-hold):
  - `vol-scaled momentum 7d`: worst **+18.8 %**, median +69 %. A 15 % stop-loss
    checked every 5 min lifts that to worst **+28.9 %**, median +95 %, and cuts
    the drawdown 42 % → 36 %. 20 % is similar; 5 % and 10 % are worse or noisy.
    The stop is live on this book. (Any stop hurt at 12 h: the cadence, not
    the stop, was the problem.)
  - `chart + breadth 60 %`: worst **-29.8 %** at 36 h, -3.5 % at 12 h. It no
    longer passes on this window; every stop level made it worse. It keeps
    running as the comparison book, with no stop.
- Plain momentum, reversal, breakout, volume-surge, "hold while rising" all
  **failed** the worst-case test. See `lab_lean.out`, `lab_exit.out`. Thinner
  coins (floor 500) made the worst case worse: `lab_lean.out` question A.
- The positioning data (funding, OI, long/short) that motivated the project has
  **never been tested**: Binance keeps 30 days and the collector restarted
  2026-09-05 on the PC. Around 2026-10-05 there is enough history to try
  `features.score(chart, pos)`.

Decision rule agreed with the owner: real money only when worst-case
out-of-sample excess over buy-and-hold is > 0 **and** 30 days of paper match.

## What is running, and where

Moved to the Windows PC (F:\CryptoBro) on 2026-09-05. Three scheduled tasks,
registered by `deploy\windows\install.ps1`, run from logon with no window
(user tasks: a reboot nobody logs in after runs nothing, same as launchd was):

| task | does | log |
|---|---|---|
| `CryptoBro collector` | `collector.py` forever, restarted a minute after any exit | `logs\collector.log` |
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
- Live trading is only `trade.py --live`, which demands typing `yes i am sure`.

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
| `trade.py`, `binance_th.py`, `binance_client.py`, `risk.py` | the only path to real orders |
| `cloud/` | Firebase: `functions/step.py` + `main.py` (the 12 h step), `public/index.html` (the panel) |
| `deploy/` | systemd units + `install.sh` for a VPS; `deploy/windows/` scheduled tasks + `install.ps1` for a PC |
| `lab_*.out` | measured results, see above |
