"""Backfill progress as a self-refreshing HTML page.

    python3 progress.py            # write progress.html once
    python3 progress.py --watch    # rewrite every 15s until the backfill ends

While the backfill holds its write lock the row count cannot be read, so
progress is estimated two independent ways and both are shown. Once the lock
clears the numbers come straight from the database and stop being estimates.
"""
import os
import sqlite3
import subprocess
import sys
import time

DB = "data.db"
OUT = "progress.html"
SYMBOLS = 384              # USDT pairs listed on Binance TH
DAYS = 90
BARS_PER_SYMBOL = DAYS * 24 * 12
EXPECTED_ROWS = SYMBOLS * BARS_PER_SYMBOL
BASELINE_BYTES = 294 * 1024 * 1024   # database size before the TH backfill started


def backfill_pid():
    """The process holding a write lock on the database, if any."""
    try:
        out = subprocess.run(["lsof", "-t", DB], capture_output=True, text=True,
                             timeout=5).stdout.split()
    except Exception:
        return None
    for pid in out:
        try:
            cmd = subprocess.run(["ps", "-p", pid, "-o", "command="],
                                 capture_output=True, text=True, timeout=5).stdout
            if "Python" in cmd or "python" in cmd:
                return int(pid)
        except Exception:
            continue
    return None


def elapsed_seconds(pid):
    if not pid:
        return None
    try:
        et = subprocess.run(["ps", "-p", str(pid), "-o", "etime="],
                            capture_output=True, text=True, timeout=5).stdout.strip()
    except Exception:
        return None
    if not et:
        return None
    days, _, rest = et.rpartition("-")
    parts = [int(p) for p in rest.split(":")]
    while len(parts) < 3:
        parts.insert(0, 0)
    secs = parts[0] * 3600 + parts[1] * 60 + parts[2]
    return secs + (int(days) * 86400 if days else 0)


def exact():
    """Real counts, only possible once the write lock is gone."""
    try:
        c = sqlite3.connect(f"file:{DB}?mode=ro", uri=True, timeout=2)
        rows, syms = c.execute(
            "SELECT count(*), count(DISTINCT symbol) FROM th_klines").fetchone()
        return {"rows": rows, "symbols": syms}
    except Exception:
        return None


def snapshot():
    size = os.path.getsize(DB) if os.path.exists(DB) else 0
    pid = backfill_pid()
    el = elapsed_seconds(pid)
    got = exact()

    if got:
        pct = min(100.0, got["rows"] / EXPECTED_ROWS * 100)
        return {"live": bool(pid), "exact": True, "pct": pct, "size": size,
                "elapsed": el, "rows": got["rows"], "symbols_done": got["symbols"],
                "eta": None}

    # Locked. Estimate from bytes written and from time spent, and show both:
    # the spread between them is the honest error bar.
    by_size = (size - BASELINE_BYTES) / (EXPECTED_ROWS * 85) * 100
    per_symbol = 12.0                       # ~26 paged calls plus pacing
    by_time = (el / (SYMBOLS * per_symbol) * 100) if el else 0.0
    pct = max(0.0, min(99.0, (by_size + by_time) / 2))
    eta = (el / pct * (100 - pct)) if el and pct > 1 else None
    return {"live": bool(pid), "exact": False, "pct": pct, "size": size,
            "elapsed": el, "by_size": max(0.0, by_size), "by_time": by_time,
            "eta": eta, "rows": None, "symbols_done": None}


def hms(s):
    if not s:
        return "-"
    s = int(s)
    return f"{s // 3600}h {s % 3600 // 60}m" if s >= 3600 else f"{s // 60}m {s % 60}s"


def render(s):
    done = not s["live"]
    label = "complete" if done else ("measured" if s["exact"] else "estimated")
    detail = (f"{s['rows']:,} rows from {s['symbols_done']} symbols"
              if s["exact"] else
              f"by size {s['by_size']:.0f}% &middot; by elapsed time {s['by_time']:.0f}%")
    return f"""<title>Backfill progress</title>
<meta http-equiv="refresh" content="15">
<style>
  :root {{
    --bg:#fbfaf9; --fg:#1a1a1a; --muted:#6b6b6b; --line:#e3e0dc;
    --bar:#2f6f4e; --track:#eceae7; --card:#fff;
  }}
  @media (prefers-color-scheme: dark) {{
    :root:not([data-theme="light"]) {{
      --bg:#1a1a19; --fg:#eeece8; --muted:#9a9691; --line:#333230;
      --bar:#5fa87c; --track:#2a2927; --card:#232220;
    }}
  }}
  body {{ background:var(--bg); color:var(--fg); font:16px/1.5 -apple-system,
         BlinkMacSystemFont,"Segoe UI",sans-serif; margin:0; padding:40px 20px; }}
  .card {{ max-width:560px; margin:0 auto; background:var(--card);
           border:1px solid var(--line); border-radius:14px; padding:32px; }}
  h1 {{ font-size:15px; font-weight:600; margin:0 0 4px; letter-spacing:.01em; }}
  .sub {{ color:var(--muted); font-size:13px; margin:0 0 28px; }}
  .pct {{ font-size:56px; font-weight:650; letter-spacing:-.02em; line-height:1;
          font-variant-numeric:tabular-nums; }}
  .tag {{ font-size:12px; color:var(--muted); margin-left:10px; font-weight:400; }}
  .track {{ height:10px; background:var(--track); border-radius:99px;
            overflow:hidden; margin:22px 0 26px; }}
  .fill {{ height:100%; width:{s['pct']:.1f}%; background:var(--bar);
           border-radius:99px; transition:width .4s ease; }}
  table {{ width:100%; border-collapse:collapse; font-size:14px; }}
  td {{ padding:9px 0; border-top:1px solid var(--line); }}
  td:last-child {{ text-align:right; font-variant-numeric:tabular-nums; }}
  td:first-child {{ color:var(--muted); }}
  .note {{ font-size:12px; color:var(--muted); margin-top:24px; line-height:1.6; }}
</style>
<div class="card">
  <h1>Binance TH backfill</h1>
  <p class="sub">{SYMBOLS} USDT pairs &middot; {DAYS} days of 5m candles</p>
  <div class="pct">{s['pct']:.0f}%<span class="tag">{label}</span></div>
  <div class="track"><div class="fill"></div></div>
  <table>
    <tr><td>progress detail</td><td>{detail}</td></tr>
    <tr><td>database size</td><td>{s['size'] / 1048576:.0f} MB</td></tr>
    <tr><td>elapsed</td><td>{hms(s['elapsed'])}</td></tr>
    <tr><td>estimated remaining</td><td>{hms(s['eta'])}</td></tr>
    <tr><td>status</td><td>{'running' if s['live'] else 'finished'}</td></tr>
  </table>
  <p class="note">{'Row counts are read directly from the database.'
    if s['exact'] else
    'The backfill holds a write lock, so rows cannot be counted yet. Two '
    'independent estimates are shown above; the gap between them is the error bar.'}
  <br>Refreshes every 15 seconds. Updated {time.strftime('%H:%M:%S')}.</p>
</div>"""


def main():
    while True:
        s = snapshot()
        with open(OUT, "w") as f:
            f.write(render(s))
        print(f"{s['pct']:.0f}% {'running' if s['live'] else 'finished'} "
              f"{s['size'] / 1048576:.0f} MB")
        if "--watch" not in sys.argv or not s["live"]:
            return
        time.sleep(15)


if __name__ == "__main__":
    main()
