"""Draws fig_flow.png - the data flow of smoothdash (used in the report and video)."""
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.patches import FancyBboxPatch

fig, ax = plt.subplots(figsize=(13, 4.9)); ax.set_xlim(0, 13); ax.set_ylim(0, 4.9); ax.axis("off")
def box(x, y, w, h, title, body, fc):
    ax.add_patch(FancyBboxPatch((x, y), w, h, boxstyle="round,pad=0.02,rounding_size=0.12", fc=fc, ec="#33475b", lw=1.3))
    ax.text(x + w / 2, y + h - 0.22, title, ha="center", va="top", fontsize=11, weight="bold", color="#1f2a44")
    ax.text(x + w / 2, y + h - 0.58, body, ha="center", va="top", fontsize=8.6, color="#222", linespacing=1.35)
def arrow(x1, y1, x2, y2, label="", dy=0.1):
    ax.annotate("", (x2, y2), (x1, y1), arrowprops=dict(arrowstyle="-|>", lw=1.6, color="#33475b"))
    if label: ax.text((x1 + x2) / 2, (y1 + y2) / 2 + dy, label, ha="center", fontsize=7.5, color="#0f5c8c", style="italic")
ax.text(0.15, 4.68, "PRODUCER (Python)", fontsize=10, weight="bold", color="#0f7c7c")
ax.text(0.15, 2.12, "CONSUMER (browser, JavaScript)", fontsize=10, weight="bold", color="#8c3f0f")
ax.plot([0.1, 12.9], [2.4, 2.4], ls="--", color="#aaa", lw=1)
box(0.15, 2.65, 2.0, 1.85, "Phone", "IoT Remote app\naccelerometer x, y, z\n2 samples/s", "#eef3f8")
box(2.9, 2.65, 2.2, 1.85, "Arduino IoT Cloud", "Thing variables\nacc_x, acc_y, acc_z\n(synced)\nMQTT: jitter, stalls,\nbursts", "#eef3f8")
box(5.85, 2.65, 3.1, 1.85, "LiveStream.push()", "on_write callback per variable\n1. reject None / NaN\n2. re-time onto steady clock\n3. seq-numbered ring buffer\n    (thread-safe, bounded)\n4. append to CSV log", "#e3f2ef")
box(9.7, 2.65, 3.15, 1.85, "JSON endpoint", "GET /_smoothdash/<id>?cursor=n\nreturns only samples with\nseq > n  (deltas)\n+ server time for clock sync\nfirst call: last window only", "#e3f2ef")
box(9.7, 0.1, 3.15, 1.75, "Fetch loop", "every poll_ms (200 ms)\noutside React / Dash callbacks\nmoves cursor forward\nkeeps min clock offset", "#fbeee3")
box(5.85, 0.1, 3.1, 1.75, "Jitter buffer", "per-channel queue of\n(t, value) waiting for\ntheir playout time\nT = now − delay_s", "#fbeee3")
box(0.15, 0.1, 4.95, 1.75, "Playout loop (requestAnimationFrame, ≤ fps)", "1. release samples with t ≤ T → Plotly.extendTraces\n    (append in place, trim points older than the window)\n2. axis-only relayout: x-range = [T − window, T], y eased 8%/frame\n3. newest segment interpolated to T on SVG overlay\n4. frame budget: skip a frame if the last one ran long", "#fbeee3")
arrow(2.15, 3.55, 2.9, 3.55, "data")
arrow(5.1, 3.55, 5.85, 3.55, "on_write")
arrow(8.95, 3.55, 9.7, 3.55, "since()")
arrow(11.27, 2.65, 11.27, 1.85, "")
arrow(9.7, 0.95, 8.95, 0.95, "queue")
arrow(5.85, 0.95, 5.1, 0.95, "due")
ax.text(11.4, 2.22, "HTTP / JSON", fontsize=7.5, color="#0f5c8c", style="italic")
plt.tight_layout(); plt.savefig("fig_flow.png", dpi=160)
