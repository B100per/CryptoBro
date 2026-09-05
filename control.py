"""Start and stop the paper trader from a browser, and watch it run.

    CONTROL_TOKEN=change-me python3 control.py               # http://127.0.0.1:8787
    CONTROL_TOKEN=change-me python3 control.py --port 8787 --interval 43200

One process does both jobs: it serves the page, and while "running" is on it
steps every book in STRATEGIES every `interval` seconds. Start and Stop flip a flag that
is written to control_state.json, so a restart remembers where it was.

Paper only. Nothing in this file, or in paper.py beneath it, can send an
order: the exchange client is not imported and no key is read. Live trading
stays behind trade.py and its typed confirmation, on purpose.

Binds to 127.0.0.1 by default. On a server, put it behind an SSH tunnel or a
TLS proxy; a token over plain HTTP on the open internet is not a lock.
"""
import hmac
import html
import json
import os
import secrets
import sys
import threading
import time
from collections import deque
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs

import paper
from dashboard import spark

STATE_FILE = os.environ.get("CONTROL_STATE", "control_state.json")
TOKEN = os.environ.get("CONTROL_TOKEN", "")
DEFAULT_INTERVAL = 43200          # 12h, the cadence the forward test runs at
MARK_EVERY = 300                  # 5 min: value the books at live prices, trading nothing
LOG = deque(maxlen=60)

# The rules the lab kept: worst case across start times positive, on coins a
# real order could fill. Each keeps its own book so they can be compared.
STRATEGIES = [
    {"name": "chart + breadth 60%", "db": "paper_chart.db",
     "rule": "chart", "breadth_floor": 0.6, "min_vol": 2000, "min_score": 0.5},
    {"name": "vol-scaled momentum 7d", "db": "paper_volmom.db",
     "rule": "volmom", "breadth_floor": 0.0, "min_vol": 2000, "min_score": 0.0},
]
SESSIONS = set()
STEP_LOCK = threading.Lock()


def log(msg):
    LOG.append(f"{time.strftime('%Y-%m-%d %H:%M:%S')}  {msg}")


# ── state ────────────────────────────────────────────────────────────────

def load_state():
    try:
        with open(STATE_FILE) as f:
            s = json.load(f)
    except (OSError, ValueError):
        s = {}
    s.setdefault("running", False)
    s.setdefault("interval", DEFAULT_INTERVAL)
    s.setdefault("next_step", 0)
    s.setdefault("last_step", 0)
    return s


def save_state(s):
    tmp = STATE_FILE + ".tmp"
    with open(tmp, "w") as f:
        json.dump(s, f)
    os.replace(tmp, STATE_FILE)


def set_running(on):
    s = load_state()
    s["running"] = bool(on)
    if on and s["next_step"] < time.time():
        s["next_step"] = time.time()        # first step right away
    save_state(s)
    log("started" if on else "stopped")
    return s


def run_step(reason):
    """One paper step, serialised so a click and the clock cannot overlap."""
    out = []
    with STEP_LOCK:
        for st in STRATEGIES:
            try:
                r = paper.step(paper.db(st["db"]), rule=st["rule"],
                               breadth_floor=st["breadth_floor"], min_vol=st["min_vol"],
                               min_score=st["min_score"])
                log(f"{st['name']} ({reason}): equity {r['equity']:.2f}, "
                    f"holding {', '.join(r['picks']) or 'nothing'}")
                out.append(r)
            except Exception as e:       # a bad API reply must not kill the server
                log(f"{st['name']} failed ({reason}): {e}")
                out.append(None)
    return out


def run_mark():
    """Value every book at live prices, no trading: the curve between steps.
    Not logged; 288 lines a day would bury the steps in the activity panel."""
    with STEP_LOCK:
        for st in STRATEGIES:
            try:
                paper.mark(paper.db(st["db"]))
            except Exception as e:
                log(f"{st['name']} mark failed: {e}")


def tick(now=None):
    """Run a step if one is due, else a mark if one is due. Called every few
    seconds by the scheduler. Returns True only when a step ran."""
    now = now or time.time()
    s = load_state()
    if not s["running"]:
        return False
    if now >= s["next_step"]:
        run_step("schedule")
        s = load_state()
        s["last_step"] = now
        s["next_step"] = now + s["interval"]
        s["next_mark"] = now + MARK_EVERY
        save_state(s)
        return True
    if now >= s.get("next_mark", 0):
        run_mark()
        s["next_mark"] = now + MARK_EVERY
        save_state(s)
    return False


def scheduler():
    while True:
        try:
            tick()
        except Exception as e:
            log(f"scheduler error: {e}")
        time.sleep(5)


# ── page ─────────────────────────────────────────────────────────────────

CSS = """
:root{color-scheme:light dark;--bg:#f6f6f2;--fg:#1a1a18;--mut:#74746c;--line:#e0e0d8;
 --card:#fff;--up:#0d7a45;--down:#b53a22;--accent:#1f5fbf;--accent-fg:#fff;--warn:#8a6d00;--warn-bg:#fff6d6}
@media(prefers-color-scheme:dark){:root{--bg:#121211;--fg:#ebebe5;--mut:#8f8f86;--line:#2a2a26;
 --card:#1b1b19;--up:#3fc07f;--down:#ef6d50;--accent:#5b8ee6;--accent-fg:#0b1220;--warn:#f0c94c;--warn-bg:#2a2410}}
*{box-sizing:border-box}
body{margin:0;background:var(--bg);color:var(--fg);
 font:15px/1.55 ui-sans-serif,-apple-system,"Segoe UI",Inter,sans-serif}
.wrap{max-width:920px;margin:0 auto;padding:32px 20px 48px}
header{display:flex;align-items:center;gap:14px;margin-bottom:26px}
header h1{font-size:17px;margin:0;letter-spacing:.02em}
.badge{font-size:11px;letter-spacing:.12em;text-transform:uppercase;font-weight:700;
 padding:4px 9px;border-radius:999px;border:1px solid var(--line);color:var(--mut)}
.badge.warn{color:var(--warn);background:var(--warn-bg);border-color:transparent}
.pill{margin-left:auto;display:inline-flex;align-items:center;gap:8px;font-weight:600;font-size:13px}
.pill i{width:9px;height:9px;border-radius:50%;background:var(--mut);display:inline-block}
.pill.on i{background:var(--up);box-shadow:0 0 0 4px color-mix(in srgb,var(--up) 22%,transparent)}
.grid{display:grid;grid-template-columns:1fr 1fr;gap:18px}
@media(max-width:700px){.grid{grid-template-columns:1fr}}
.card{background:var(--card);border:1px solid var(--line);border-radius:14px;padding:22px}
.card h2{margin:0 0 12px;font-size:11.5px;letter-spacing:.12em;text-transform:uppercase;color:var(--mut)}
.equity{font-size:44px;font-weight:650;letter-spacing:-.025em;font-variant-numeric:tabular-nums;line-height:1.1}
.equity small{font-size:15px;color:var(--mut);font-weight:500;margin-left:6px}
.ret{font-size:20px;font-weight:650;margin-left:12px}
.up{color:var(--up)}.down{color:var(--down)}
.meta{color:var(--mut);font-size:13px;margin:6px 0 0}
.actions{display:flex;gap:10px;flex-wrap:wrap;margin-top:18px}
button{font:inherit;font-weight:600;padding:11px 18px;border-radius:10px;border:1px solid var(--line);
 background:var(--card);color:var(--fg);cursor:pointer}
button.primary{background:var(--accent);color:var(--accent-fg);border-color:transparent}
button.danger{color:var(--down)}
button:disabled{opacity:.45;cursor:default}
.chart{width:100%;height:auto;margin-top:14px}
.chart polyline{fill:none;stroke:var(--up);stroke-width:2;stroke-linejoin:round}
.chart.down polyline{stroke:var(--down)}
.zero{stroke:var(--line);stroke-dasharray:3 4}
.lbl{fill:var(--mut);font-size:11px;font-family:ui-monospace,monospace}
table{width:100%;border-collapse:collapse;font-variant-numeric:tabular-nums}
th,td{text-align:left;padding:8px 6px;border-bottom:1px solid var(--line);font-size:13.5px}
th{color:var(--mut);font-size:11px;letter-spacing:.1em;text-transform:uppercase}
td.n{text-align:right;font-family:ui-monospace,monospace;font-size:12.5px}
pre{margin:0;font:12.5px/1.6 ui-monospace,monospace;white-space:pre-wrap;color:var(--fg)}
.muted{color:var(--mut)}
.login{max-width:380px;margin:12vh auto 0}
input[type=password]{width:100%;font:inherit;padding:11px 12px;border-radius:10px;
 border:1px solid var(--line);background:var(--bg);color:var(--fg);margin:12px 0}
footer{margin-top:26px;color:var(--mut);font-size:12.5px}
"""


def page_login(error=""):
    return f"""<!doctype html><meta charset=utf-8><meta name=viewport content="width=device-width,initial-scale=1">
<title>CryptoBro — sign in</title><style>{CSS}</style>
<div class="wrap login"><div class=card>
<header><h1>CryptoBro</h1><span class="badge warn">paper only</span></header>
<form method=post action=/login>
<label class=muted>Control token</label>
<input type=password name=token autofocus autocomplete=current-password>
{f'<p class=down>{html.escape(error)}</p>' if error else ''}
<button class=primary type=submit>Sign in</button></form></div></div>"""


def book(st):
    c = paper.db(st["db"])
    s = paper.status(c)
    rows = c.execute("SELECT ts, equity FROM equity ORDER BY ts").fetchall()
    return s, rows


def card(st):
    s, rows = book(st)
    equity = s.get("equity", paper.START_EQUITY)
    ret = s.get("return_pct", 0.0)
    cls = "up" if ret >= 0 else "down"
    pos = "".join(f"<tr><td>{html.escape(sym)}</td><td class=n>{u:,.4f}</td><td class=n>{e:,.6g}</td></tr>"
                  for sym, u, e in s.get("positions", []))
    gate = f" · cash when breadth &lt; {st['breadth_floor']:.0%}" if st["breadth_floor"] else ""
    return f"""<div class=card>
  <h2>{html.escape(st['name'])}</h2>
  <div><span class=equity>{equity:,.2f}<small>USDT</small></span><span class="ret {cls}">{ret:+.2f}%</span></div>
  <p class=meta>{s.get('steps', 0)} steps · max drawdown {s.get('max_drawdown_pct', 0):.2f}%
  · top {paper.TOP} · liquidity ≥ {st['min_vol']:,} USDT/5m{gate}</p>
  {spark(rows, h=170)}
  <table><tr><th>coin</th><th class=n>units</th><th class=n>entry</th></tr>
  {pos or '<tr><td colspan=3 class=muted>nothing held</td></tr>'}</table>
</div>"""


def page_main(sid):
    st = load_state()
    now = time.time()
    nxt = st["next_step"] - now
    when = ("due now" if nxt <= 0 else f"in {nxt / 3600:.1f} h") if st["running"] else "—"
    last = time.strftime("%d %b %H:%M", time.localtime(st["last_step"])) if st["last_step"] else "never"
    logs = html.escape("\n".join(reversed(LOG))) or "no activity yet"
    csrf = f'<input type=hidden name=csrf value="{sid}">'
    return f"""<!doctype html><meta charset=utf-8><meta name=viewport content="width=device-width,initial-scale=1">
<meta http-equiv=refresh content=20><title>CryptoBro</title><style>{CSS}</style>
<div class=wrap>
<header><h1>CryptoBro</h1><span class="badge warn">paper only · no real money</span>
<span class="pill {'on' if st['running'] else ''}"><i></i>{'Running' if st['running'] else 'Stopped'}</span></header>

<div class=card style="margin-bottom:18px">
  <form method=post class=actions style="margin:0">
    {csrf}
    <button class=primary formaction=/start {'disabled' if st['running'] else ''}>Start</button>
    <button class=danger formaction=/stop {'' if st['running'] else 'disabled'}>Stop</button>
    <button formaction=/step>Run one step now</button>
    <span class=meta style="align-self:center">every {st['interval'] / 3600:g} h · last step {last} · next {when}</span>
    <button formaction=/logout style="margin-left:auto">Sign out</button>
  </form>
</div>

<div class=grid>{''.join(card(x) for x in STRATEGIES)}</div>

<div class=card style="margin-top:18px"><h2>Activity</h2><pre>{logs}</pre></div>
<footer>Two rules run side by side on the same schedule, each in its own paper book, so the market
can say which one the backtest described. Between steps the books are valued at live prices every
5 minutes, trading nothing, so the curve is real time. Buys and sells are rows in a local database; the
exchange client is not loaded by this process, so it cannot place an order even if asked. Refreshes every 20 s.</footer>
</div>"""


# ── http ─────────────────────────────────────────────────────────────────

class Handler(BaseHTTPRequestHandler):
    server_version = "CryptoBro/0.1"

    def log_message(self, *a):          # keep the terminal quiet; LOG has what matters
        pass

    def sid(self):
        c = self.headers.get("Cookie", "")
        for part in c.split(";"):
            k, _, v = part.strip().partition("=")
            if k == "sid" and v in SESSIONS:
                return v
        return None

    def send_page(self, body, status=HTTPStatus.OK, headers=()):
        data = body.encode()
        self.send_response(status)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        for k, v in headers:
            self.send_header(k, v)
        self.end_headers()
        self.wfile.write(data)

    def redirect(self, to="/", headers=()):
        self.send_response(HTTPStatus.SEE_OTHER)
        self.send_header("Location", to)
        self.send_header("Content-Length", "0")
        for k, v in headers:
            self.send_header(k, v)
        self.end_headers()

    def form(self):
        n = int(self.headers.get("Content-Length") or 0)
        return {k: v[0] for k, v in parse_qs(self.rfile.read(n).decode()).items()}

    def do_GET(self):
        if self.path.startswith("/api/status"):
            if not self.sid():
                return self.send_page("forbidden", HTTPStatus.FORBIDDEN)
            st = load_state()
            body = json.dumps({**st, "books": {
                x["name"]: {k: v for k, v in paper.status(paper.db(x["db"])).items()
                            if k != "positions"} for x in STRATEGIES}})
            data = body.encode()
            self.send_response(HTTPStatus.OK)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            return self.wfile.write(data)
        sid = self.sid()
        self.send_page(page_main(sid) if sid else page_login())

    def do_POST(self):
        f = self.form()
        if self.path == "/login":
            if TOKEN and hmac.compare_digest(f.get("token", ""), TOKEN):
                sid = secrets.token_urlsafe(24)
                SESSIONS.add(sid)
                log("signed in")
                return self.redirect("/", [("Set-Cookie", f"sid={sid}; HttpOnly; SameSite=Strict; Path=/")])
            time.sleep(0.5)                      # blunt the guessing rate
            return self.send_page(page_login("wrong token"), HTTPStatus.FORBIDDEN)

        sid = self.sid()
        # Double-submit: the form must carry the session id it was rendered with,
        # so a page on another site cannot press these buttons with your cookie.
        if not sid or not hmac.compare_digest(f.get("csrf", ""), sid):
            return self.send_page("forbidden", HTTPStatus.FORBIDDEN)
        if self.path == "/start":
            set_running(True)
        elif self.path == "/stop":
            set_running(False)
        elif self.path == "/step":
            run_step("manual")
        elif self.path == "/logout":
            SESSIONS.discard(sid)
            return self.redirect("/", [("Set-Cookie", "sid=; Max-Age=0; Path=/")])
        else:
            return self.send_page("not found", HTTPStatus.NOT_FOUND)
        self.redirect("/")


def serve(host="127.0.0.1", port=8787):
    srv = ThreadingHTTPServer((host, port), Handler)
    threading.Thread(target=scheduler, daemon=True).start()
    log(f"control panel on http://{host}:{srv.server_port}")
    return srv


def main():
    if not TOKEN:
        sys.exit("set CONTROL_TOKEN to something long and private first")
    arg = lambda n, d, c=str: c(sys.argv[sys.argv.index(n) + 1]) if n in sys.argv else d
    s = load_state()
    s["interval"] = arg("--interval", s["interval"], int)
    save_state(s)
    srv = serve(arg("--host", "127.0.0.1"), arg("--port", 8787, int))
    print(LOG[-1])
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
