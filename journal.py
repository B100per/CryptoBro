"""Trade log. Every order the bot sends, appended to CSV and JSON.

    python3 journal.py           # summary
    python3 journal.py --tail 20 # last N entries

CSV for spreadsheets, JSON for code. Both append-only: this is the record of
what actually happened, so nothing here is ever rewritten.
"""
import csv
import json
import os
import sys
import time

DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "logs")
CSV_FILE = os.path.join(DIR, "trades.csv")
JSON_FILE = os.path.join(DIR, "trades.json")
FIELDS = ["ts", "date", "side", "pair", "qty", "price", "value", "quote",
          "score", "live", "order_id", "error"]


def record(side, pair, qty, price, quote, score=None, live=False,
           order_id=None, error=None, ts=None, directory=None):
    d = directory or DIR
    os.makedirs(d, exist_ok=True)
    ts = ts or int(time.time() * 1000)
    row = {"ts": ts,
           "date": time.strftime("%Y-%m-%d %H:%M:%S", time.gmtime(ts / 1000)),
           "side": side, "pair": pair, "qty": qty, "price": price,
           "value": round(qty * price, 8), "quote": quote, "score": score,
           "live": live, "order_id": order_id, "error": error}

    csv_path = os.path.join(d, "trades.csv")
    new = not os.path.exists(csv_path)
    with open(csv_path, "a", newline="") as f:
        w = csv.DictWriter(f, fieldnames=FIELDS)
        if new:
            w.writeheader()
        w.writerow(row)

    json_path = os.path.join(d, "trades.json")
    entries = read(d)
    entries.append(row)
    with open(json_path, "w") as f:
        json.dump(entries, f, indent=2)
    return row


def read(directory=None):
    try:
        with open(os.path.join(directory or DIR, "trades.json")) as f:
            return json.load(f)
    except (FileNotFoundError, ValueError):
        return []


def summary(directory=None):
    rows = read(directory)
    live = [r for r in rows if r.get("live")]
    failed = [r for r in rows if r.get("error")]
    return {"entries": len(rows), "live": len(live), "dry_run": len(rows) - len(live),
            "failed": len(failed),
            "bought": sum(r["value"] for r in live if r["side"] == "BUY" and not r.get("error")),
            "sold": sum(r["value"] for r in live if r["side"] == "SELL" and not r.get("error"))}


if __name__ == "__main__":
    if "--tail" in sys.argv:
        n = int(sys.argv[sys.argv.index("--tail") + 1])
        for r in read()[-n:]:
            print(f"{r['date']}  {r['side']:<4} {r['pair']:<12} {r['value']:>10.2f} "
                  f"{r['quote']}  live={r['live']}" + (f"  ERROR {r['error']}" if r.get("error") else ""))
        sys.exit(0)
    for k, v in summary().items():
        print(f"{k:<10} {v}")
