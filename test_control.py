import json, os, sqlite3, tempfile, threading, time, urllib.request, urllib.error, urllib.parse
import notify, paper

notify.send = lambda *a, **k: False
d = tempfile.mkdtemp()
paper.DB = os.path.join(d, "paper.db")
os.environ["CONTROL_STATE"] = os.path.join(d, "state.json")
os.environ["CONTROL_TOKEN"] = "s3cret"
import control
control.STATE_FILE = os.environ["CONTROL_STATE"]
control.TOKEN = "s3cret"

# Stub the market: fixed prices, fixed ranking. No network in a test.
paper.prices = lambda: {"AAAUSDT": 10.0, "BBBUSDT": 20.0}
paper.scores = lambda quote="USDT": ({"AAAUSDT": 2.0, "BBBUSDT": 1.5}, "th_klines")
paper.TOP = 2

# Scheduler logic, no sockets: a stopped panel never steps, a running one steps
# when due and then waits a full interval.
assert control.tick(now=1000) is False
control.set_running(True)
s = control.load_state(); s["interval"] = 100; s["next_step"] = 1000; control.save_state(s)
assert control.tick(now=999) is False
assert control.tick(now=1000) is True
assert control.load_state()["next_step"] == 1100
assert control.tick(now=1050) is False
assert paper.status(paper.db())["steps"] == 1
control.set_running(False)
assert control.tick(now=5000) is False, "stopped must mean stopped"

# HTTP: unauthenticated sees the login page and cannot press anything.
srv = control.serve("127.0.0.1", 0)
threading.Thread(target=srv.serve_forever, daemon=True).start()
base = f"http://127.0.0.1:{srv.server_port}"

def call(path, data=None, cookie=None, code=None):
    req = urllib.request.Request(base + path, data=urllib.parse.urlencode(data).encode() if data is not None else None)
    if cookie: req.add_header("Cookie", cookie)
    try:
        with urllib.request.urlopen(req) as r:
            return r.status, r.read().decode(), r.headers
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode(), e.headers

st, body, _ = call("/")
assert st == 200 and "Control token" in body and "Start" not in body
st, body, _ = call("/start", {"csrf": "x"})
assert st == 403
st, body, _ = call("/login", {"token": "wrong"})
assert st == 403 and "wrong token" in body

# Right token → cookie → main page with the buttons.
class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *a, **k): return None
opener = urllib.request.build_opener(NoRedirect)
req = urllib.request.Request(base + "/login", data=b"token=s3cret")
try:
    opener.open(req)
    assert False, "expected a redirect"
except urllib.error.HTTPError as e:
    assert e.code == 303
    cookie = e.headers["Set-Cookie"].split(";")[0]
    assert "HttpOnly" in e.headers["Set-Cookie"]
sid = cookie.split("=", 1)[1]
st, body, _ = call("/", cookie=cookie)
assert st == 200 and ">Start<" in body and "paper only" in body

# CSRF: the session cookie alone is not enough to press Start.
st, _, _ = call("/start", {"csrf": "forged"}, cookie=cookie)
assert st == 403 and control.load_state()["running"] is False
req = urllib.request.Request(base + "/start", data=f"csrf={sid}".encode()); req.add_header("Cookie", cookie)
try: opener.open(req)
except urllib.error.HTTPError as e: assert e.code == 303
assert control.load_state()["running"] is True
req = urllib.request.Request(base + "/stop", data=f"csrf={sid}".encode()); req.add_header("Cookie", cookie)
try: opener.open(req)
except urllib.error.HTTPError as e: assert e.code == 303
assert control.load_state()["running"] is False

st, body, _ = call("/api/status", cookie=cookie)
assert st == 200 and json.loads(body)["running"] is False

# Nothing in the panel's import graph can reach the exchange with an order.
import sys
assert "binance_th" not in sys.modules and "binance_client" not in sys.modules
srv.shutdown()
print("ok")
