"""
Offline check of the two buffering decisions in smoothdash, using the replay's network model
(12 minutes of my Week 8 phone data, 2 Hz, jitter and stalls):
  1. re-timing arrival times onto a steady clock (LiveStream retime=True), and
  2. choosing the playout delay (live_graph delay_s).
Writes fig_retiming.png and fig_delay_tradeoff.png and prints the numbers used in the report.
"""
import itertools
import random

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

from replay_client import ReplayCloudClient
from smoothdash import _Retimer

N = 1440                                                     # 12 minutes at 2 Hz
x_vals = pd.read_csv("cloud_export/accelerometer_x.csv")["value"].to_numpy()
events = [e for e in itertools.islice(ReplayCloudClient(seed=8).schedule(0.0), 3 * N) if e[1] == "acc_x"]
true_t = np.array([e[2] for e in events])                    # when the phone took each reading
arrive = np.array([e[3] for e in events])                    # when it reached Python
rt = _Retimer()
retimed = np.array([rt(a) for a in arrive])

def describe(name, t):
    gaps = np.diff(t)
    err = (t - true_t) - np.median(t - true_t)              # timing error after removing the constant lag
    return dict(method=name, gap_mean=gaps.mean(), gap_sd=gaps.std(), gap_min=gaps.min(), gap_max=gaps.max(),
                bunched=(gaps < 0.1).mean() * 100, err_sd=err.std() * 1000, err_p95=np.percentile(abs(err), 95) * 1000)

tab = pd.DataFrame([describe("Arrival time (no re-timing)", arrive), describe("Re-timed (smoothdash)", retimed)])
print(tab.round(3).to_string(index=False))

# playout delay trade-off: a sample is "late" if it reaches the browser after its playout time.
# Browser receipt = arrival in Python + wait for the next 200 ms poll + ~15 ms request.
rng = random.Random(1)
receipt = arrive + np.array([rng.uniform(0, 0.2) for _ in arrive]) + 0.015
delays = np.round(np.arange(0.2, 2.01, 0.1), 2)
late_rt = [((retimed + d) < receipt).mean() * 100 for d in delays]
late_raw = [((arrive + d) < receipt).mean() * 100 for d in delays]
lag_rt = [np.median(retimed + d - true_t) for d in delays]
print("\ndelay  late%(retimed)  late%(arrival)  screen lag (s)")
for d, a, b, l in zip(delays, late_rt, late_raw, lag_rt):
    if d in (0.3, 0.5, 0.8, 1.0, 1.5, 2.0):
        print(f"{d:4.1f}   {a:6.2f}         {b:6.2f}         {l:5.2f}")

# ---- figures ----
fig, ax = plt.subplots(1, 2, figsize=(12, 4.2))
bins = np.linspace(0, 1.4, 57)
ax[0].hist(np.diff(arrive), bins=bins, alpha=0.6, label="arrival times", color="#d62728")
ax[0].hist(np.diff(retimed), bins=bins, alpha=0.75, label="re-timed", color="#1f77b4")
ax[0].axvline(0.5, color="k", ls=":", lw=1)
ax[0].set_xlabel("time between consecutive acc_x samples (s)"); ax[0].set_ylabel("count")
ax[0].set_title("Gaps between samples (phone samples every 0.5 s)"); ax[0].legend()
s = slice(200, 240)                                          # 20 s that include a stall
ax[1].plot(true_t[s] - true_t[s][0], x_vals[s], "k-", lw=1, alpha=0.35, label="true shape (phone clock)")
ax[1].plot(arrive[s] - true_t[s][0] - np.median(arrive - true_t), x_vals[s], "o-", ms=3, color="#d62728",
           label="plotted at arrival time")
ax[1].plot(retimed[s] - true_t[s][0] - np.median(retimed - true_t), x_vals[s], "s-", ms=3, color="#1f77b4",
           label="plotted at re-timed time")
ax[1].set_xlabel("seconds"); ax[1].set_ylabel("acc_x (m/s²)"); ax[1].set_title("Effect on the drawn waveform")
ax[1].legend(fontsize=8, loc="lower left")
plt.tight_layout(); plt.savefig("fig_retiming.png", dpi=150)

fig, ax = plt.subplots(figsize=(7.5, 4))
ax.plot(delays, late_rt, "o-", color="#1f77b4", label="samples drawn late (%)")
ax.set_xlabel("playout delay delay_s (s)"); ax.set_ylabel("samples drawn late (%)", color="#1f77b4")
ax2 = ax.twinx()
ax2.plot(delays, lag_rt, "s--", color="#ff7f0e", label="phone-to-screen lag (s)")
ax2.set_ylabel("phone-to-screen lag (s)", color="#ff7f0e")
ax.axvline(1.0, color="k", ls=":", lw=1); ax.text(1.03, max(late_rt) * 0.85, "default 1.0 s", fontsize=9)
ax.set_title("Choosing the playout delay: fewer late samples vs more lag"); ax.grid(alpha=0.3)
plt.tight_layout(); plt.savefig("fig_delay_tradeoff.png", dpi=150)
print("saved fig_retiming.png, fig_delay_tradeoff.png")
