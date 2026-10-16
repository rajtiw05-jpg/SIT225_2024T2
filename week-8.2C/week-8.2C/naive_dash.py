"""
Baseline for comparison - the Week 8 approach: wait until N new samples have arrived for each axis, then
build a brand-new figure from those N samples and send the whole figure to the browser.

    python naive_dash.py --replay      (port 8051)
"""
import argparse
import threading
import time
from collections import deque

import plotly.graph_objects as go
from dash import Dash, Input, Output, dcc, html, no_update

N = 20                                              # 20 samples = 10 s at 2 Hz

ap = argparse.ArgumentParser()
ap.add_argument("--replay", action="store_true")
ap.add_argument("--port", type=int, default=8051)
args = ap.parse_args()

buf = {a: deque() for a in "xyz"}
lock = threading.Lock()


def on_value(axis, v):
    with lock:
        buf[axis].append((time.time(), float(v)))


if args.replay:
    from replay_client import ReplayCloudClient as Client
else:
    from arduino_iot_cloud import ArduinoCloudClient as Client
client = Client(device_id="<id>", username="<id>", password="<key>")
for a in "xyz":
    client.register(f"acc_{a}", value=None, on_write=lambda cl, v, a=a: on_value(a, v))
threading.Thread(target=client.start, daemon=True).start()

app = Dash(__name__, title="Naive update")
app.layout = html.Div(style={"fontFamily": "Arial", "padding": "14px", "background": "#f3f5f8"}, children=[
    html.H2("Week 8 approach – redraw every N samples", style={"margin": "4px 8px 10px"}),
    html.Div(dcc.Graph(id="g", style={"height": "330px"}, config={"displayModeBar": False}),
             style={"background": "white", "borderRadius": "8px", "padding": "6px"}),
    dcc.Interval(id="tick", interval=500),
])


@app.callback(Output("g", "figure"), Input("tick", "n_intervals"))
def update(_):
    with lock:
        if min(len(buf[a]) for a in "xyz") < N:
            return no_update                         # keep waiting for N new samples
        chunk = {a: [buf[a].popleft() for _ in range(N)] for a in "xyz"}
    fig = go.Figure()
    for a, c in zip("xyz", ["#1f77b4", "#d62728", "#2ca02c"]):
        t = [p[0] * 1000 for p in chunk[a]]
        fig.add_scatter(x=t, y=[p[1] for p in chunk[a]], mode="lines", name=a, line=dict(color=c, width=2))
    fig.update_layout(title="Accelerometer x, y, z (m/s²)", height=330, margin=dict(l=60, r=20, t=50, b=40),
                      xaxis=dict(type="date"), yaxis=dict(title="m/s²"), plot_bgcolor="white")
    return fig


if __name__ == "__main__":
    app.run(port=args.port, debug=False)
