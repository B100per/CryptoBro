import progress

assert progress.hms(None) == "-"
assert progress.hms(45) == "0m 45s"
assert progress.hms(3700) == "1h 1m"

# a locked database must still render, with both estimates and no crash
locked = {"live": True, "exact": False, "pct": 40.0, "size": 500 * 1048576,
          "elapsed": 1800, "by_size": 35.0, "by_time": 45.0, "eta": 2700,
          "rows": None, "symbols_done": None}
html = progress.render(locked)
assert "40%" in html and "estimated" in html and "width:40.0%" in html
assert "by size 35%" in html and "by elapsed time 45%" in html
assert "cannot be counted yet" in html

# once unlocked it reports real counts and stops hedging
done = {"live": False, "exact": True, "pct": 100.0, "size": 900 * 1048576,
        "elapsed": 4000, "rows": 9_953_280, "symbols_done": 384, "eta": None}
html = progress.render(done)
assert "100%" in html and "complete" in html and "9,953,280 rows" in html
assert "finished" in html and "cannot be counted yet" not in html

# a fresh start must not render a negative bar width
early = dict(locked, pct=0.0, by_size=0.0, by_time=0.0, elapsed=1, eta=None)
assert "width:0.0%" in progress.render(early)
print("ok")
