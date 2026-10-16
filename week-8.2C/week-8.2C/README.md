# week-8.2C – Live smooth Plotly Dash update for smartphone accelerometer data

SIT225 Credit Task 5C · Raj Tiwary (223185472)

`smoothdash.py` makes Plotly Dash line graphs scroll smoothly while live data arrives, so the viewer never
sees a graph being replaced. It works for any continuous numeric data, not only the phone accelerometer.

```python
from smoothdash import LiveStream, live_graph

stream = LiveStream(["x", "y", "z"])                         # 1. named channels
app.layout = html.Div([live_graph(app, stream, "acc")])      # 2. one call per graph
stream.push("x", 0.42)                                       # 3. push values from any thread
```

## Files

| File | What it is |
|---|---|
| `smoothdash.py` | The wrapper: `LiveStream` (thread-safe buffer with re-timing) and `live_graph()` (Dash component) |
| `phone_smooth_dash.py` | Phone → Arduino IoT Cloud → Python → smooth Dash graphs (x, y, z combined and per axis) |
| `naive_dash.py` | Week 8 approach for comparison: new figure every N = 20 samples |
| `demo_any_signal.py` | The same function on other data: CPU load (4 Hz) and a 50 Hz synthetic sensor |
| `replay_client.py` | Offline stand-in for `ArduinoCloudClient`: replays `cloud_export/` with network jitter and stalls |
| `evaluate_retiming.py` | Offline evaluation of re-timing and playout delay → `fig_retiming.png`, `fig_delay_tradeoff.png` |
| `measure_in_browser.py` | Measures what a viewer sees in Chromium → `browser_metrics.csv`, `fig_filmstrip.png` |
| `test_smoothdash.py` | Checks of LiveStream: bad values, deltas, reset, re-timing, thread safety |
| `draw_flow.py` | Draws `fig_flow.png` (data-flow diagram) |
| `cloud_export/` | My Week 8 phone recording (Arduino Cloud export, 2 Hz, 12 min) |
| `accelerometer_live_*.csv` | Data logged by `phone_smooth_dash.py` during the recorded run (time, channel, value) |
| `fig_*.png`, `browser_metrics.csv` | Generated graphs and measurements used in the report |

## Run

```bash
pip install dash pandas numpy matplotlib psutil playwright arduino-iot-cloud
python phone_smooth_dash.py            # live: set DEVICE_ID and SECRET_KEY of the Python device first
python phone_smooth_dash.py --replay   # offline replay of cloud_export/
# open http://127.0.0.1:8050
```

Tested with Python 3.13, Dash 4.4.1 (plotly.js 4.1.1), Flask 3.1, pandas 3.0, NumPy 2.5.
