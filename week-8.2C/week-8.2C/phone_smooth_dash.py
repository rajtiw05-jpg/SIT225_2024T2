"""
SIT225 Credit Task 5C - live smooth Plotly Dash update for smartphone accelerometer data.

Phone (Arduino IoT Remote app) -> Arduino IoT Cloud -> this Python device -> smoothdash -> browser.

    python phone_smooth_dash.py                 # live: needs DEVICE_ID / SECRET_KEY of the Python device
    python phone_smooth_dash.py --replay        # offline: replays my Week 8 export with realistic jitter
Then open http://127.0.0.1:8050
"""
import argparse
import threading
from datetime import datetime

from dash import Dash, html

from smoothdash import LiveStream, live_graph

DEVICE_ID = "<your Python device id>"
SECRET_KEY = "<your secret key>"

ap = argparse.ArgumentParser()
ap.add_argument("--replay", action="store_true", help="replay cloud_export/*.csv instead of the live cloud")
ap.add_argument("--port", type=int, default=8050)
ap.add_argument("--delay", type=float, default=1.0, help="playout delay in seconds")
args = ap.parse_args()

# 1. one stream with three channels; every accepted sample is also logged to a CSV data file
stream = LiveStream(["x", "y", "z"], csv_path=f"accelerometer_live_{datetime.now():%Y%m%d_%H%M%S}.csv")

# 2. Arduino Cloud: each synced variable's on_write callback just pushes its value
if args.replay:
    from replay_client import ReplayCloudClient as Client
else:
    from arduino_iot_cloud import ArduinoCloudClient as Client
client = Client(device_id=DEVICE_ID, username=DEVICE_ID, password=SECRET_KEY)
for axis in "xyz":
    client.register(f"acc_{axis}", value=None, on_write=lambda cl, v, a=axis: stream.push(a, v))
threading.Thread(target=client.start, daemon=True).start()   # client.start() blocks, so give it its own thread

# 3. Dash: one combined graph and one graph per axis, all from the same stream
app = Dash(__name__, title="Smooth accelerometer stream")
card = {"background": "white", "borderRadius": "8px", "boxShadow": "0 1px 4px rgba(0,0,0,.12)", "padding": "6px"}
app.layout = html.Div(style={"fontFamily": "Arial", "background": "#f3f5f8", "padding": "14px"}, children=[
    html.H2("Smartphone accelerometer – live (smooth update)", style={"margin": "4px 8px 10px"}),
    html.Div(live_graph(app, stream, "acc", window_s=20, delay_s=args.delay, height=330,
                        title="Accelerometer x, y, z (m/s²)", y_title="m/s²"), style=card),
    html.Div(style={"display": "grid", "gridTemplateColumns": "1fr 1fr 1fr", "gap": "12px", "marginTop": "12px"},
             children=[html.Div(live_graph(app, stream, f"acc-{a}", channels=[a], window_s=10, delay_s=args.delay,
                                           height=230, title=f"acc_{a}", y_title="m/s²",
                                           colors=[c]), style=card)
                       for a, c in zip("xyz", ["#1f77b4", "#d62728", "#2ca02c"])]),
])

if __name__ == "__main__":
    app.run(port=args.port, debug=False)
