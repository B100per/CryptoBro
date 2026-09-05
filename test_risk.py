import json, os, tempfile
from risk import check

p = os.path.join(tempfile.mkdtemp(), "state.json")

# first call anchors the day at whatever equity is now
ok, why, s = check(1000.0, limit=0.05, path=p, today="2026-09-05")
assert ok and s["anchor"] == 1000.0 and not s["tripped"]

# a 4% drop is inside the limit
ok, _, s = check(960.0, limit=0.05, path=p, today="2026-09-05")
assert ok and abs(s["drawdown"] - 0.04) < 1e-9

# 5% trips it
ok, why, s = check(950.0, limit=0.05, path=p, today="2026-09-05")
assert not ok and s["tripped"] and "5.00%" in why

# and the trip is sticky: recovering the same day does not re-enable buying
ok, _, s = check(1000.0, limit=0.05, path=p, today="2026-09-05")
assert not ok and s["tripped"]

# a restart must not forget the trip
assert json.load(open(p))["tripped"] is True

# a new UTC day re-anchors and clears it
ok, _, s = check(950.0, limit=0.05, path=p, today="2026-09-06")
assert ok and s["anchor"] == 950.0 and not s["tripped"]

# a missing or corrupt state file must not crash the caller
open(p, "w").write("{ not json")
ok, _, s = check(500.0, limit=0.05, path=p, today="2026-09-07")
assert ok and s["anchor"] == 500.0
print("ok")
