from regime import efficiency_ratio, percentile, atr_percentile, classify

# a straight line covers all its ground in one direction
assert abs(efficiency_ratio([1, 2, 3, 4, 5], n=4) - 1.0) < 1e-9

# a sawtooth that ends where it started travels far and arrives nowhere
assert efficiency_ratio([1, 2, 1, 2, 1], n=4) == 0.0

# a noisy uptrend lands in between, and above a clean reversal
noisy_up = [1, 3, 2, 4, 3, 5, 4, 6]
assert 0.0 < efficiency_ratio(noisy_up, n=7) < 1.0
assert efficiency_ratio(noisy_up, n=7) > efficiency_ratio([1, 5, 1], n=2)

assert efficiency_ratio([5], n=10) == 0.0        # too short to say anything
assert efficiency_ratio([5, 5, 5], n=2) == 0.0   # no movement at all, no division by zero

assert percentile([1, 2, 3, 4], 3) == 0.75
assert percentile([], 3) == 0.5                  # unknown, not zero

n = 300
trend_c = [100 * (1.002 ** i) for i in range(n)]
chop_c = [100 + (2 if i % 2 else -2) for i in range(n)]
hi = lambda c: [x * 1.002 for x in c]
lo = lambda c: [x * 0.998 for x in c]

name, tradable, d = classify(hi(trend_c), lo(trend_c), trend_c)
assert name == "trend" and tradable, (name, d)

name, tradable, d = classify(hi(chop_c), lo(chop_c), chop_c)
assert name == "chop" and not tradable, (name, d)

# a market whose volatility has just exploded is refused even while trending
spike = trend_c[:-10] + [trend_c[-11] * (1.25 ** i) for i in range(1, 11)]
name, tradable, _ = classify(hi(spike), lo(spike), spike)
assert not tradable and name == "volatile", name
print("ok")
