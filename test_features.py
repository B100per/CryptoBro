from features import ema, atr, structure, chart_read, score

assert abs(ema([1, 1, 1, 1], 3) - 1.0) < 1e-9
assert ema([1, 2, 3, 4, 5], 3) > 3.0          # weighted to recent bars

# true range of a flat-gap series is just the bar range
assert abs(atr([2, 2, 2], [1, 1, 1], [1.5, 1.5, 1.5, 1.5], n=3) - 1.0) < 1e-9

up_h = list(range(10, 34))
up_l = [h - 2 for h in up_h]
assert structure(up_h, up_l, seg=12) == 1.0
assert structure(up_h[::-1], up_l[::-1], seg=12) == -1.0
assert structure([5] * 24, [4] * 24, seg=12) == 0.0

rising = [(i, i + 1, i - 1, i + 0.5, 100.0) for i in range(100, 200)]
c = chart_read(rising)
assert c and c["trend"] > 0 and c["structure"] == 1.0
assert c["regime"] == "trend" and c["tradable"]

# a chart in chop must score below anything the planner would ever buy
chop = [(100, 102, 98, 100 + (2 if i % 2 else -2), 100.0) for i in range(100)]
cc = chart_read(chop)
assert cc and not cc["tradable"]
assert score(cc, None) == -99.0
assert score(cc, None, gate=False) > -99.0      # the gate must be the only reason
assert chart_read(rising[:10]) is None        # too few bars to read anything

falling = rising[::-1]
assert chart_read(falling)["trend"] < 0

# crowded longs must score below the identical chart with neutral funding
hot = {"funding": 0.001, "top_pos": 1.0, "global_acct": 1.0, "oi_change": 0.0}
calm = {"funding": 0.0, "top_pos": 1.0, "global_acct": 1.0, "oi_change": 0.0}
assert score(c, hot) < score(c, calm)

# smart money long while retail is not should score above the reverse
smart = {"funding": 0.0, "top_pos": 2.0, "global_acct": 1.0, "oi_change": 0.0}
dumb = {"funding": 0.0, "top_pos": 1.0, "global_acct": 2.0, "oi_change": 0.0}
assert score(c, smart) > score(c, dumb)
print("ok")
