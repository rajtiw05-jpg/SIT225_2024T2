"""Quick checks of LiveStream (run: python test_smoothdash.py)."""
import math
import threading

from smoothdash import LiveStream, _Retimer

# bad values are rejected and counted
s = LiveStream(["x", "y"])
assert s.push("x", 1.5) and not s.push("x", None) and not s.push("x", math.nan) and not s.push("y", "abc")
assert s.stats == {"accepted": 1, "rejected": 3}
try:
    s.push("q", 1.0); raise SystemExit("unknown channel should raise")
except KeyError:
    pass

# since() returns only newer samples, grouped by channel and in order
s = LiveStream(["x", "y"], retime=False)
for i in range(5):
    s.push_many(t=100 + i, x=i, y=-i)
cur, out, reset = s.since(0)
out = {k: [list(a), list(b)] for k, (a, b) in out.items()}
assert cur == 10 and out["x"] == [[100, 101, 102, 103, 104], [0, 1, 2, 3, 4]] and not reset
cur2, out2, _ = s.since(6, channels=["y"])
assert cur2 == 10 and {k: [list(a), list(b)] for k, (a, b) in out2.items()} == {"y": [[103, 104], [-3, -4]]}
assert s.since(10) == (10, {}, False)
_, out3, _ = s.since(0, min_t=103)
assert list(out3["x"][0]) == [103, 104]

# a browser that fell behind the history limit is told to reset
s = LiveStream(["x"], retime=False, history=3)
for i in range(10):
    s.push("x", i, t=i)
assert s.since(2)[2] is True and s.since(7)[2] is False

# re-timing spreads a burst back onto a steady 0.5 s grid
r = _Retimer()
arr = [i * 0.5 for i in range(20)] + [11.0, 11.01, 11.02]     # stall from 9.5 s, then a burst of 3
t = [r(a) for a in arr]
gaps = [b - a for a, b in zip(t[-4:], t[-3:])]
assert all(0.3 < g < 0.7 for g in gaps), gaps
assert all(x <= a + 1e-9 for x, a in zip(t, arr))             # never placed after its arrival

# thread safety: 4 threads x 5000 pushes, nothing lost or duplicated
s = LiveStream(["a", "b", "c", "d"], history=100000)
th = [threading.Thread(target=lambda c=c: [s.push(c, i) for i in range(5000)]) for c in "abcd"]
[x.start() for x in th]; [x.join() for x in th]
cur, out, _ = s.since(0)
assert cur == 20000 and all(len(out[c][1]) == 5000 for c in "abcd")
print("all LiveStream checks passed")
