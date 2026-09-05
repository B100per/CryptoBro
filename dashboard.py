"""Live view of the paper run and the signal lab, as a self-refreshing page.

    python3 dashboard.py                     # write dashboard.html once
    python3 dashboard.py --watch             # rewrite every 10s
    python3 dashboard.py --db live30.db --lab lab.out

Reads whatever exists and says so when something is missing, rather than
failing: the lab takes an hour and the page has to be useful before it lands.
"""
import html
import os
import sqlite3
import sys
import time

REFRESH = 10
OUT = os.environ.get("DASHBOARD_OUT", "dashboard.html")


def curve(db):
    if not os.path.exists(db):
        return [], []
    c = sqlite3.connect(f"file:{db}?mode=ro", uri=True, timeout=5)
    try:
        rows = c.execute("SELECT ts, equity FROM equity ORDER BY ts").fetchall()
        pos = c.execute("SELECT symbol, units, entry FROM positions "
                        "ORDER BY symbol").fetchall()
    except sqlite3.Error:
        return [], []
    finally:
        c.close()
    return rows, pos


def spark(rows, w=760, h=220, pad=28):
    """Equity as an inline SVG. No chart library: it is one polyline."""
    if len(rows) < 2:
        return '<p class="muted">waiting for the second mark…</p>'
    ys = [e for _, e in rows]
    lo, hi = min(ys), max(ys)
    span = (hi - lo) or (hi * 1e-6) or 1.0
    n = len(rows) - 1
    pts = " ".join(
        f"{pad + i / n * (w - 2 * pad):.1f},{h - pad - (e - lo) / span * (h - 2 * pad):.1f}"
        for i, e in enumerate(ys))
    start, last = ys[0], ys[-1]
    cls = "up" if last >= start else "down"
    base = h - pad - (start - lo) / span * (h - 2 * pad)
    return f'''<svg viewBox="0 0 {w} {h}" class="chart {cls}" role="img"
     aria-label="equity from {start:.2f} to {last:.2f} USDT">
  <line x1="{pad}" y1="{base:.1f}" x2="{w - pad}" y2="{base:.1f}" class="zero"/>
  <polyline points="{pts}"/>
  <text x="{pad}" y="16" class="lbl">{hi:,.2f}</text>
  <text x="{pad}" y="{h - 6}" class="lbl">{lo:,.2f}</text>
</svg>'''


def render(db, lab_path):
    rows, pos = curve(db)
    start = rows[0][1] if rows else 0.0
    last = rows[-1][1] if rows else 0.0
    pct = (last - start) / start * 100 if start else 0.0
    age = f"{(time.time() * 1000 - rows[-1][0]) / 60000:.1f} min ago" if rows else "-"

    lab = ""
    if lab_path and os.path.exists(lab_path):
        lab = open(lab_path).read().strip()
    lab_body = (f"<pre>{html.escape(lab)}</pre>" if lab.count("\n") > 1 else
                '<p class="muted">still loading 9.9M bars and running 90 backtests. '
                'Nothing to show until the first row lands.</p>')

    pos_rows = "".join(
        f"<tr><td>{html.escape(s)}</td><td class=n>{u:,.6f}</td>"
        f"<td class=n>{e:,.8g}</td></tr>" for s, u, e in pos)

    return f"""<!doctype html><meta charset=utf-8>
<meta http-equiv=refresh content={REFRESH}>
<title>CryptoBro — live</title>
<style>
:root {{ color-scheme: light dark;
  --bg:#fbfbf9; --fg:#1c1c1a; --mut:#77776f; --line:#e2e2dc;
  --up:#0f7b46; --down:#b3341f; --card:#fff; }}
@media (prefers-color-scheme:dark) {{ :root {{
  --bg:#141412; --fg:#e8e8e2; --mut:#8d8d84; --line:#2c2c28;
  --up:#3fbf7f; --down:#e8674c; --card:#1c1c19; }} }}
* {{ box-sizing:border-box }}
body {{ margin:0; padding:28px; background:var(--bg); color:var(--fg);
  font:14px/1.55 ui-sans-serif,-apple-system,"Segoe UI",sans-serif; }}
h1 {{ font-size:15px; letter-spacing:.14em; text-transform:uppercase;
  color:var(--mut); font-weight:600; margin:0 0 20px }}
h2 {{ font-size:13px; letter-spacing:.1em; text-transform:uppercase;
  color:var(--mut); font-weight:600; margin:0 0 12px }}
.wrap {{ max-width:860px; margin:0 auto }}
.card {{ background:var(--card); border:1px solid var(--line); border-radius:10px;
  padding:20px; margin-bottom:18px }}
.big {{ font-size:38px; font-weight:600; letter-spacing:-.02em;
  font-variant-numeric:tabular-nums }}
.pct {{ font-size:19px; font-weight:600; margin-left:10px }}
.up {{ color:var(--up) }} .down {{ color:var(--down) }}
.muted {{ color:var(--mut); margin:0 }}
.chart {{ width:100%; height:auto; margin-top:12px }}
.chart polyline {{ fill:none; stroke-width:2; stroke-linejoin:round;
  stroke:var(--up) }}
.chart.down polyline {{ stroke:var(--down) }}
.zero {{ stroke:var(--line); stroke-width:1; stroke-dasharray:3 4 }}
.lbl {{ fill:var(--mut); font-size:11px; font-family:ui-monospace,monospace }}
table {{ border-collapse:collapse; width:100%; font-variant-numeric:tabular-nums }}
th,td {{ text-align:left; padding:7px 10px; border-bottom:1px solid var(--line) }}
th {{ color:var(--mut); font-weight:600; font-size:11px;
  letter-spacing:.08em; text-transform:uppercase }}
td.n {{ text-align:right; font-family:ui-monospace,monospace; font-size:13px }}
pre {{ margin:0; overflow-x:auto; font-family:ui-monospace,monospace;
  font-size:12.5px; line-height:1.6 }}
.note {{ border-left:3px solid var(--line); padding-left:14px; color:var(--mut);
  margin:16px 0 0 }}
</style>
<div class=wrap>
<h1>CryptoBro — paper only, no real money</h1>

<div class=card>
  <h2>30-minute live run</h2>
  <div><span class="big">{last:,.4f}</span><span class="pct {'up' if pct >= 0 else 'down'}">{pct:+.3f}%</span></div>
  <p class=muted>{len(rows)} marks · last {age} · started at {start:,.2f} USDT</p>
  {spark(rows)}
  <p class=note>Bought once from the live ranking, then marked to market every
  minute without rebalancing. Half an hour cannot measure an edge — crypto moves
  more than that in noise alone. It measures whether the live pipeline is
  correct.</p>
</div>

<div class=card>
  <h2>Holdings</h2>
  <table><tr><th>symbol</th><th class=n>units</th><th class=n>entry</th></tr>
  {pos_rows or '<tr><td colspan=3 class=muted>nothing held</td></tr>'}</table>
</div>

<div class=card>
  <h2>Signal lab — excess over buy-and-hold, worst case across start times</h2>
  {lab_body}
  <p class=note>A rule is worth keeping only if it is positive across start
  times <em>and</em> across rebalance periods. One tall number beside two poor
  ones is timing luck, which is what this table exists to expose. Reversal is
  in the list on purpose: if betting on winners and on losers both look
  profitable, the sample is describing noise.</p>
</div>

<p class=muted>refreshes every {REFRESH}s · {time.strftime('%H:%M:%S')}</p>
</div>"""


def main():
    def arg(name, default):
        return sys.argv[sys.argv.index(name) + 1] if name in sys.argv else default

    db = arg("--db", os.environ.get("PAPER_DB", "paper.db"))
    lab = arg("--lab", "lab.out")
    while True:
        with open(OUT, "w") as f:
            f.write(render(db, lab))
        if "--watch" not in sys.argv:
            print(os.path.abspath(OUT))
            return
        time.sleep(REFRESH)


if __name__ == "__main__":
    main()
