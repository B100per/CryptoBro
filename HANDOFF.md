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
  Never rebalance faster than 12 h.
- Plain momentum, reversal, breakout, volume-surge, "hold while rising" all
  **failed** the worst-case test. See `lab_lean.out`, `lab_exit.out`.
- Two rules **passed** (worst case across start times positive, on coins with
  ≥ 2,000 USDT/5 min volume): `chart + breadth 60 %` and `vol-scaled momentum 7d`.
  Passing one 3-month test is a reason to forward-test, not to fund.
- The positioning data (funding, OI, long/short) that motivated the project has
  **never been tested**: Binance keeps 30 days and the collector started 2026-09-04.
  Around 2026-10-05 there is enough history to try `features.score(chart, pos)`.

Decision rule agreed with the owner: real money only when worst-case
out-of-sample excess over buy-and-hold is > 0 **and** 30 days of paper match.

## What is running, and where

On the Mac this was written on (**stops if that Mac sleeps or is shut down**):

| thing | how | note |
|---|---|---|
| collector (5 m klines + positioning → `data.db`) | launchd `com.b100per.cryptobro` | `data.db` is 1.2 GB, **not in git** |
| retention rollup 04:30 | launchd `com.b100per.cryptobro.retention` | |
| control panel + both paper books | `python3 control.py` on `127.0.0.1:8787` | token in `.env` as `CONTROL_TOKEN` |
| dashboard watcher | `dashboard.py --watch` → `dashboard.html` | lab results view |

Paper books: `paper_chart.db`, `paper_volmom.db`, schedule state `control_state.json` —
**not in git**. Copy them if you want the history; otherwise they restart from 1000 USDT.
The old launchd paper agent is unloaded; the panel is the only scheduler.

## To resume on the new machine

```bash
git clone https://github.com/B100per/CryptoBro.git && cd CryptoBro
cp /path/from/old/mac/.env .          # or recreate, see below — never commit it
for f in test_*.py signals.py book.py; do python3 $f; done     # all should print ok
python3 collector.py --once           # small data.db to start with
CONTROL_TOKEN=$(grep CONTROL_TOKEN .env | cut -d= -f2) python3 control.py
open http://127.0.0.1:8787
```

`.env` keys (**never in git**, never in chat): `BINANCE_KEY`, `BINANCE_SECRET`
(binance.th key, spot only, **no withdrawal**, IP-restricted), `DISCORD_WEBHOOK`,
`CONTROL_TOKEN` (any long random string), `MAX_NOTIONAL_THB=1000`.

A full 90-day backfill (`collector.py --history 90`) takes ~1 h 20 and 1.2 GB.
The backtests need it; the paper books do not (they read the last ~2016 bars).

## Firebase (in progress, branch merged as skeleton)

Project: `cryptobro-591d7`. Plan: Hosting serves the panel, a scheduled Python
Cloud Function runs the step every 12 h fetching klines live from binance.th,
Firestore holds the books, rules restrict everything to one Google account.

Done: `cloud/firebase.json`, `.firebaserc`, `firestore.rules`, `functions/requirements.txt`,
`functions/build.sh`. **Not done:** `functions/main.py` (the step), `public/index.html`
(the page), tests. Both are ~150 lines each; the pure logic they need is in `book.py`.

Before it can deploy, the owner must: enable the Blaze plan (Functions need it;
free tier covers this load), `firebase login`, put their email in
`firestore.rules` (OWNER_EMAIL), paste the web app config into the page.
Deploy is `cd cloud && functions/build.sh && firebase deploy`.
Research (backtests, lab) stays local: it needs the 1.2 GB database.

## Conventions

- New feature → new branch → tests → merge to main → push. Bug fixes on main.
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
| `deploy/` | systemd units + `install.sh` for a VPS; `control.service` for the panel |
| `lab_*.out` | measured results, see above |
