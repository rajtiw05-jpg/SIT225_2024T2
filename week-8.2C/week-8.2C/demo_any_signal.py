"""
Reusing smoothdash for other continuous data - no knowledge of the buffering needed.
Two unrelated sources: this computer's CPU load (4 Hz) and a fast synthetic sensor (50 Hz).

    python demo_any_signal.py      (port 8052)
"""
import math
import random
import threading
import time

import psutil
from dash import Dash, html

from smoothdash import LiveStream, live_graph

cpu = LiveStream(["cpu"])
sensor = LiveStream(["signal", "filtered"])


def produce():
    t0, f, last_cpu = time.time(), 0.0, 0.0
    while True:
        t = time.time() - t0
        raw = math.sin(2 * math.pi * 0.4 * t) + 0.3 * math.sin(2 * math.pi * 2.1 * t) + random.gauss(0, 0.15)
        f += 0.15 * (raw - f)                             # simple low-pass filter
        sensor.push_many(signal=raw, filtered=f)
        if time.time() - last_cpu >= 0.25:
            cpu.push("cpu", psutil.cpu_percent(interval=None)); last_cpu = time.time()
        time.sleep(0.02)


threading.Thread(target=produce, daemon=True).start()

app = Dash(__name__, title="smoothdash – any signal")
app.layout = html.Div(style={"fontFamily": "Arial", "padding": "14px"}, children=[
    html.H2("Same function, other data"),
    live_graph(app, cpu, "cpu", window_s=30, delay_s=0.5, y_range=[0, 100], title="CPU load (%) – 4 Hz",
               colors=["#ff7f0e"], height=260),
    live_graph(app, sensor, "sig", window_s=8, delay_s=0.6, title="Synthetic sensor – 50 Hz",
               colors=["#9bb7d4", "#1f3b73"], height=300),
])

if __name__ == "__main__":
    app.run(port=8052, debug=False)
