import csv, json, os, tempfile
import journal

d = tempfile.mkdtemp()

journal.record("BUY", "SOLTHB", 0.5, 3400.0, "THB", score=2.1, live=True,
               order_id="a1", ts=1788500000000, directory=d)
journal.record("SELL", "SOLTHB", 0.5, 3500.0, "THB", live=True,
               order_id="a2", ts=1788600000000, directory=d)
journal.record("BUY", "BTCTHB", 0.001, 2_700_000.0, "THB", live=False,
               ts=1788700000000, directory=d)
journal.record("BUY", "XRPTHB", 10.0, 60.0, "THB", live=True,
               error="insufficient balance", ts=1788800000000, directory=d)

rows = journal.read(d)
assert len(rows) == 4
assert rows[0]["value"] == 1700.0                  # qty * price
assert rows[0]["date"].startswith("2026-")

# the CSV must carry the same entries, header written once
with open(os.path.join(d, "trades.csv")) as f:
    csv_rows = list(csv.DictReader(f))
assert len(csv_rows) == 4 and csv_rows[0]["pair"] == "SOLTHB"

s = journal.summary(d)
assert s == {"entries": 4, "live": 3, "dry_run": 1, "failed": 1,
             "bought": 1700.0, "sold": 1750.0}   # the failed buy is not counted as spent

# appending must never lose earlier entries
journal.record("BUY", "ETHTHB", 0.01, 84_000.0, "THB", live=True, ts=1788900000000, directory=d)
assert len(journal.read(d)) == 5

# a corrupt json log must not stop the next trade being recorded
open(os.path.join(d, "trades.json"), "w").write("{ broken")
journal.record("BUY", "BNBTHB", 0.1, 30_000.0, "THB", live=True, ts=1789000000000, directory=d)
assert len(journal.read(d)) == 1
print("ok")
