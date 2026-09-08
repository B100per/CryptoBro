"""One-off: repair books/volmom after the 2026-09-08 watch bug (fix/cloud-watch-merge).

paper_watch wrote with set(merge=True), so SOPHUSDT stayed in `held` after its
stop and was sold again every 5 minutes. This rebuilds the true book from the
fills: cash after the rebalance plus the first (genuine) STOP sale, the four
remaining coins, and the 5-minute curve with the phantom sales taken out.
Refuses to write if the reconstruction does not add up.

    python repair_volmom.py            # show what it would write
    python repair_volmom.py --write    # write it

Talks to Firestore through the Firebase CLI's own MCP server, so it uses the
CLI login and needs no service-account key. Delete this file once run.
"""
import datetime
import json
import os
import subprocess
import sys

DRY = "--write" not in sys.argv
ROOT = "projects/cryptobro-591d7/databases/(default)/documents/"
HERE = os.path.dirname(os.path.abspath(__file__))
f = lambda ms: datetime.datetime.fromtimestamp(int(ms) / 1000).strftime("%d %b %H:%M:%S")

p = subprocess.Popen(["firebase.cmd" if os.name == "nt" else "firebase",
                      "mcp", "--only", "firestore", "--dir", HERE],
                     stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
n = [0]


def rpc(method, params=None):
    n[0] += 1
    i = n[0]
    p.stdin.write(json.dumps({"jsonrpc": "2.0", "id": i, "method": method, "params": params or {}}) + "\n")
    p.stdin.flush()
    while True:
        line = p.stdout.readline()
        if not line:
            raise SystemExit("mcp died: " + p.stderr.read()[-2000:])
        try:
            m = json.loads(line)
        except ValueError:
            continue
        if m.get("id") == i:
            return m


def call(name, args):
    r = rpc("tools/call", {"name": name, "arguments": args})
    txt = "".join(c.get("text", "") for c in r["result"]["content"])
    return json.loads(txt) if txt.strip().startswith("{") else txt


def val(v):
    for k in ("doubleValue", "integerValue", "stringValue", "booleanValue"):
        if k in v:
            return int(v[k]) if k == "integerValue" else v[k]
    if "arrayValue" in v:
        return [val(x) for x in v["arrayValue"].get("values", [])]
    if "mapValue" in v:
        return {k: val(x) for k, x in v["mapValue"].get("fields", {}).items()}


def enc(v):
    if isinstance(v, bool):
        return {"booleanValue": v}
    if isinstance(v, int):
        return {"integerValue": str(v)}
    if isinstance(v, float):
        return {"doubleValue": v}
    if isinstance(v, str):
        return {"stringValue": v}
    if isinstance(v, list):
        return {"arrayValue": {"values": [enc(x) for x in v]}}
    if isinstance(v, dict):
        return {"mapValue": {"fields": {k: enc(x) for k, x in v.items()}}}
    raise TypeError(v)


rpc("initialize", {"protocolVersion": "2024-11-05", "capabilities": {},
                   "clientInfo": {"name": "repair", "version": "0"}})
p.stdin.write(json.dumps({"jsonrpc": "2.0", "method": "notifications/initialized"}) + "\n")
p.stdin.flush()

raw = call("firestore_get_document", {"name": ROOT + "books/volmom"})
doc = {k: val(v) for k, v in raw["fields"].items()}
fl = call("firestore_list_documents", {"parent": ROOT + "books/volmom",
                                       "collectionId": "fills", "pageSize": 300})
fills = sorted(({k: val(v) for k, v in d["fields"].items()} for d in fl["documents"]),
               key=lambda r: r["ts"])
# Only the sales the document has already absorbed: a fill written after the
# document was last marked is not yet in its cash.
stops = [r for r in fills if r["side"] == "STOP" and r["symbol"] == "SOPHUSDT"
         and r["ts"] <= doc["marked"]]
net = [r["units"] * r["price"] - r["fee"] for r in stops]
print("doc marked", f(doc["marked"]), "| SOPH stops absorbed", len(stops),
      "| genuine", f(stops[0]["ts"]), "px", stops[0]["price"])
repaired = "repaired" in doc.get("watch_note", "")
if repaired:
    print("book already repaired; only the curve is touched")
    fixed, watch = {}, list(doc["watch"])
else:
    cash0 = doc["cash"] - sum(net)
    print("cash left after the rebalance", round(cash0, 4))
    assert -1 < cash0 < 60, "reconstruction does not add up; not writing"
    true_cash = round(cash0 + net[0], 8)
    held = {s: v for s, v in doc["held"].items() if s != "SOPHUSDT"}
    marks = {s: pr for s, pr in doc["marks"].items() if s in held}
    holdings = sum(u * marks[s] for s, (u, _) in held.items())
    watch = [{"ts": pt["ts"],
              "equity": pt["equity"] - sum(x for r, x in zip(stops[1:], net[1:]) if r["ts"] <= pt["ts"])}
             for pt in doc["watch"]]
    fixed = {"cash": true_cash, "held": held, "marks": marks, "holdings": holdings,
             "equity": true_cash + holdings,
             "watch_note": "stop-loss sold SOPHUSDT (book repaired 2026-09-09: "
                           "a merge bug had re-sold it every 5 minutes)"}
    print(f"cash {doc['cash']:.2f} -> {true_cash:.2f} | equity {doc['equity']:.2f} -> "
          f"{fixed['equity']:.2f} | held {sorted(held)}")
# Between the genuine sale and the first phantom one, SOPH sat above its floor:
# still in Firestore's held, so those marks counted it twice, as cash and as a
# holding. Its price at those ticks was not kept, so the marks are dropped, not
# guessed.
double = [pt for pt in watch if stops[0]["ts"] < pt["ts"] < stops[1]["ts"]]
watch = [pt for pt in watch if pt not in double]
print("double-counted marks dropped:", [(f(pt["ts"]), round(pt["equity"], 2)) for pt in double])
fixed["watch"] = watch
print("curve last", f(watch[-1]["ts"]), round(watch[-1]["equity"], 2),
      "| min", round(min(w["equity"] for w in watch), 2),
      "| max", round(max(w["equity"] for w in watch), 2))
if not repaired:
    assert abs(fixed["equity"] - watch[-1]["equity"]) < 1.0, "document and curve disagree"
if DRY:
    print("DRY RUN, nothing written. Add --write.")
else:
    r = rpc("tools/call", {"name": "firestore_update_document", "arguments": {
        "document": {"name": ROOT + "books/volmom",
                     "fields": {k: enc(v) for k, v in fixed.items()}},
        "updateMask": {"fieldPaths": list(fixed)}}})
    ok = "error" not in r and not r["result"].get("isError")
    print("written" if ok else "FAILED", str(r)[:300])
p.terminate()
