"""
smoothdash - smooth, real-time Plotly Dash graphs for any continuous data stream.

    from smoothdash import LiveStream, live_graph

    stream = LiveStream(["x", "y", "z"])                  # 1. one stream, named channels
    app.layout = html.Div([live_graph(app, stream, "acc")])  # 2. one function call per graph
    stream.push("x", 0.42)                                # 3. push values from any thread

How it works (details in the SIT225 5C report, Q1):
  * Producer side (Python): every value is timestamped on arrival, re-timed onto a steady clock to remove
    network jitter, and stored with a sequence number in a thread-safe ring buffer.
  * Transport: the browser fetches only the samples newer than its cursor from a small JSON endpoint on the
    app's Flask server (deltas, never the whole figure, and no React re-render).
  * Consumer side (browser): a JavaScript jitter buffer holds the samples and a requestAnimationFrame loop
    plays them out on a playout clock that runs `delay_s` behind real time, like a video player.
    Points are appended with Plotly.extendTraces, the x-axis slides every frame with an axis-only relayout,
    the y-axis eases to new limits, and the newest segment is interpolated on a light SVG overlay so the
    line grows continuously. The figure is never rebuilt, so there is no visible redraw.
"""
import csv
import json
import math
import threading
import time
from collections import deque

from dash import Input, Output, dcc, html
from flask import jsonify, request

__all__ = ["LiveStream", "live_graph"]
__version__ = "1.0.0"

DEFAULT_COLORS = ["#1f77b4", "#d62728", "#2ca02c", "#9467bd", "#ff7f0e", "#17becf", "#8c564b", "#e377c2"]


class _Retimer:
    """Places arrival times of one channel onto a steady clock.

    Cloud messages arrive with jitter and in bursts, so arrival times are uneven even when the phone samples
    at a fixed rate. The sample period is estimated from the last `n` arrivals; each new sample is placed one
    period after the previous one and nudged a little (alpha) towards its real arrival time so the clock
    cannot drift. A pause longer than `gap_factor` periods is treated as a real gap and the clock resyncs.
    """

    def __init__(self, n=20, alpha=0.05, gap_factor=4.0):
        self.arrivals = deque(maxlen=n)
        self.alpha, self.gap_factor = alpha, gap_factor
        self.t = None

    def __call__(self, arrival):
        if self.arrivals and arrival - self.arrivals[-1] > self.gap_factor * max(self._period() or 0, 0.05) \
                and len(self.arrivals) > 2:
            self.arrivals.clear()                      # real gap: start estimating again
            self.t = None
        self.arrivals.append(arrival)
        p = self._period()
        if self.t is None or p is None:
            self.t = arrival
        else:
            pred = self.t + p
            self.t = min(pred + self.alpha * (arrival - pred), arrival)
        return self.t

    def _period(self):
        if len(self.arrivals) < 3:
            return None
        span = self.arrivals[-1] - self.arrivals[0]
        return span / (len(self.arrivals) - 1) if span > 0 else None


class LiveStream:
    """Thread-safe buffer for one or more named channels of continuous numeric data.

    Parameters
    ----------
    channels : list of str     Channel names, e.g. ["x", "y", "z"]. Each becomes one line on a graph.
    retime : bool              Smooth out network jitter in arrival times (default True). Set False if you
                               pass your own accurate timestamps to push().
    history : int              Samples kept in memory for browsers that connect or reconnect (default 20000).
    csv_path : str or None     If given, every accepted sample is also appended to this CSV file
                               (columns: time, channel, value).
    """

    def __init__(self, channels, retime=True, history=20000, csv_path=None):
        if not channels:
            raise ValueError("LiveStream needs at least one channel name")
        self.channels = list(channels)
        self._index = {c: i for i, c in enumerate(self.channels)}
        self._retime = {c: _Retimer() for c in self.channels} if retime else None
        self._buf = deque(maxlen=history)
        self._seq = 0
        self._lock = threading.Lock()
        self._csv = None
        if csv_path:
            f = open(csv_path, "a", newline="")
            self._csv = (f, csv.writer(f))
            if f.tell() == 0:
                self._csv[1].writerow(["time", "channel", "value"])
        self.stats = {"accepted": 0, "rejected": 0}

    def push(self, channel, value, t=None):
        """Add one value to `channel`. Safe to call from any thread (e.g. an Arduino Cloud on_write callback).
        `t` is a Unix timestamp in seconds; if omitted, the arrival time is used. None/NaN/inf are ignored."""
        try:
            v = float(value)
        except (TypeError, ValueError):
            v = math.nan
        if not math.isfinite(v):
            self.stats["rejected"] += 1
            return False
        if channel not in self._index:
            raise KeyError(f"unknown channel {channel!r}; expected one of {self.channels}")
        arrival = time.time() if t is None else float(t)
        with self._lock:
            ts = self._retime[channel](arrival) if self._retime else arrival
            self._seq += 1
            self._buf.append((self._seq, self._index[channel], ts, v))
            self.stats["accepted"] += 1
            if self._csv:
                self._csv[1].writerow([f"{ts:.3f}", channel, v])
                self._csv[0].flush()
        return True

    @property
    def seq(self):
        """Sequence number of the newest sample (0 before the first one)."""
        return self._seq

    def push_many(self, t=None, **values):
        """Push several channels at once, e.g. stream.push_many(x=1.0, y=0.2, z=9.8)."""
        for ch, v in values.items():
            self.push(ch, v, t)

    def since(self, cursor, channels=None, min_t=None):
        """Samples with sequence number > cursor, grouped per channel: (new_cursor, {name: [[t...], [v...]]}, reset).
        `reset` is True if the browser fell further behind than `history` and must clear its graph.
        `min_t` skips samples older than that time (used when a browser first connects)."""
        wanted = None if channels is None else {self._index[c] for c in channels}
        with self._lock:
            if not self._buf or self._seq <= cursor:
                return cursor, {}, False
            reset = cursor < self._buf[0][0] - 1
            out = {}
            for seq, ci, t, v in reversed(self._buf):
                if seq <= cursor or (min_t is not None and t < min_t):
                    break
                if wanted is None or ci in wanted:
                    ts, vs = out.setdefault(self.channels[ci], ([], []))
                    ts.append(round(t, 4)); vs.append(v)
            for ts, vs in out.values():
                ts.reverse(); vs.reverse()
            return self._seq, out, reset


# The browser half: a fetch loop (transport), a jitter buffer and one shared requestAnimationFrame playout loop.
_JS = r"""
function(cfg) {
  const dc = window.dash_clientside;
  if (!cfg) { return dc.no_update; }
  const S = (window.__smoothdash = window.__smoothdash || {});
  if (S[cfg.id]) { return dc.no_update; }               // already running for this graph
  const n = cfg.channels.length;
  const st = S[cfg.id] = {cfg: cfg, queue: cfg.channels.map(() => []), last: cfg.channels.map(() => null),
    offset: null, cursor: 0, paused: false, y: null, bound: null, warm: false,
    stats: {frames: 0, frameGaps: [], appended: 0, late: 0, received: 0, extendCalls: 0, workMs: 0, fetches: 0}};

  // ---- transport: fetch only the samples newer than our cursor, straight from Flask (bypasses React) ----
  async function poll() {
    try {
      const r = await fetch(cfg.url + '?cursor=' + st.cursor, {cache: 'no-store'});
      const b = await r.json();
      st.stats.fetches++;
      const off = Date.now() / 1000 - b.server_now;        // clock sync: keep the least-delayed estimate
      st.offset = st.offset === null ? off : Math.min(off, st.offset + 0.0005);
      if (b.reset) { st.queue = cfg.channels.map(() => []); st.last = cfg.channels.map(() => null); }
      const T = Date.now() / 1000 - st.offset - cfg.delay;
      for (let c = 0; c < n; c++) {
        const d = b.samples[cfg.channels[c]];
        if (!d) continue;
        for (let i = 0; i < d[0].length; i++) {
          if (st.warm && d[0][i] < T) st.stats.late++;      // arrived after its playout time
          st.queue[c].push([d[0][i], d[1][i]]); st.stats.received++;
        }
      }
      st.cursor = b.cursor; st.warm = true;
    } catch (e) { /* server restarting or offline: keep the last picture and try again */ }
    setTimeout(poll, cfg.poll_ms);
  }
  poll();

  // ---- one animation loop for every smoothdash graph on the page ----
  if (!S.__loop) {
    S.__loop = true;
    const tick = (now) => {
      requestAnimationFrame(tick);
      for (const k in S) { if (!k.startsWith('__')) frame(S[k], now); }
    };
    requestAnimationFrame(tick);
  }
  return '';

  function frame(st, now) {
    const cfg = st.cfg, n = cfg.channels.length;
    // frame budget: skip a frame if the last one took too long, so fetching and input stay responsive
    if (now - (st.lastFrame || 0) < Math.max(1000 / cfg.fps, 1.5 * (st.lastWork || 0)) - 1) return;
    const host = document.getElementById(cfg.graph_id);
    const gd = host && (host.classList.contains('js-plotly-plot') ? host : host.querySelector('.js-plotly-plot'));
    if (!gd || !gd._fullLayout || st.offset === null) return;
    if (st.bound !== gd) {                       // pause following while the user zooms/pans; double-click resumes
      gd.on('plotly_relayouting', () => { st.paused = true; });
      gd.on('plotly_doubleclick', () => { st.paused = false; });
      st.bound = gd;
    }
    if (st.lastFrame) { st.stats.frameGaps.push(now - st.lastFrame); if (st.stats.frameGaps.length > 2000) st.stats.frameGaps.shift(); }
    st.lastFrame = now; st.stats.frames++;
    const w0 = performance.now();
    const T = Date.now() / 1000 - st.offset - cfg.delay;     // playout clock
    // 1. release every sample whose time has come, appended in place (the figure is never rebuilt)
    const xs = [], ys = [], idx = [];
    for (let c = 0; c < n; c++) {
      const q = st.queue[c]; let k = 0;
      while (k < q.length && q[k][0] <= T) k++;
      if (k) {
        const due = q.splice(0, k);
        xs.push(due.map(p => p[0] * 1000)); ys.push(due.map(p => p[1])); idx.push(c);
        st.last[c] = due[due.length - 1]; st.stats.appended += k;
      }
    }
    if (idx.length) {
      // keep only points that can still be on screen (time-based trimming, capped by max_points)
      const keep = idx.map((c, j) => {
        const X = gd.data[c].x, cut = (T - cfg.window - 2) * 1000; let old = 0;
        while (old < X.length && X[old] < cut) old++;
        return Math.min(cfg.max_points, X.length - old + xs[j].length);
      });
      Plotly.extendTraces(gd, {x: xs, y: ys}, idx, keep); st.stats.extendCalls++;
    }
    // 2. slide the time window every frame and ease the y-axis towards the range of the visible data
    const lay = {};
    if (!st.paused) {
      lay['xaxis.range'] = [(T - cfg.window) * 1000, T * 1000];
      if (!cfg.y_range) {
        let lo = Infinity, hiV = -Infinity;
        for (let c = 0; c < n; c++) {
          const X = gd.data[c].x, Y = gd.data[c].y;
          for (let i = X.length - 1; i >= 0 && X[i] >= (T - cfg.window) * 1000; i--) { lo = Math.min(lo, Y[i]); hiV = Math.max(hiV, Y[i]); }
        }
        if (isFinite(lo)) {
          const pad = Math.max((hiV - lo) * 0.12, 0.5), tgt = [lo - pad, hiV + pad];
          st.y = st.y ? [st.y[0] + 0.08 * (tgt[0] - st.y[0]), st.y[1] + 0.08 * (tgt[1] - st.y[1])] : tgt;
          lay['yaxis.range'] = st.y;
        }
      }
      Plotly.relayout(gd, lay);       // axis-only relayout: cheap, the traces are not recalculated
    }
    // 3. the newest segment grows towards the next sample (linear interpolation, never extrapolation).
    //    Drawn on a small SVG overlay clipped to the plot area, because restyling a Plotly trace every
    //    frame costs about 4x more than the axis relayout.
    const fl = gd._fullLayout, xa = fl.xaxis, ya = fl.yaxis, box = gd.querySelector('.svg-container');
    if (!st.svg || !box.contains(st.svg)) {
      const NS = 'http://www.w3.org/2000/svg';
      st.svg = document.createElementNS(NS, 'svg');
      st.svg.setAttribute('style', 'position:absolute;pointer-events:none;overflow:hidden');
      st.paths = cfg.channels.map((_, c) => {
        const p = document.createElementNS(NS, 'path');
        p.setAttribute('fill', 'none'); p.setAttribute('stroke', cfg.colors[c % cfg.colors.length]);
        p.setAttribute('stroke-width', cfg.line_width); p.setAttribute('stroke-linejoin', 'round');
        st.svg.appendChild(p); return p;
      });
      box.appendChild(st.svg);
    }
    Object.assign(st.svg.style, {left: xa._offset + 'px', top: ya._offset + 'px', width: xa._length + 'px', height: ya._length + 'px'});
    for (let c = 0; c < n; c++) {
      const a = st.last[c], b = st.queue[c][0];
      let d = '';
      if (a && b && b[0] > a[0] && T > a[0]) {
        const f = Math.min(1, (T - a[0]) / (b[0] - a[0]));
        const x1 = xa.c2p(a[0] * 1000), y1 = ya.c2p(a[1]);
        const x2 = xa.c2p((a[0] + f * (b[0] - a[0])) * 1000), y2 = ya.c2p(a[1] + f * (b[1] - a[1]));
        if (isFinite(x1 + y1 + x2 + y2)) d = `M${x1.toFixed(1)},${y1.toFixed(1)}L${x2.toFixed(1)},${y2.toFixed(1)}`;
      }
      st.paths[c].setAttribute('d', d);
    }
    st.lastWork = performance.now() - w0; st.stats.workMs += st.lastWork;
  }
}
"""

_registered = set()


def live_graph(app, stream, id, channels=None, window_s=20, delay_s=1.0, fps=30, poll_ms=200, title=None,
               y_title=None, y_range=None, colors=None, height=360, max_points=5000, line_width=2):
    """Return a Dash component showing `stream` as a smoothly scrolling live line graph.

    Parameters
    ----------
    app : dash.Dash        The app; needed to register the graph's data endpoint and callback.
    stream : LiveStream    Where the data comes from.
    id : str               Unique id for this graph (several graphs can share one stream).
    channels : list        Subset of stream.channels to draw (default: all).
    window_s : float       Width of the visible time window in seconds (default 20).
    delay_s : float        Playout delay. Larger = smoother on a jittery network, smaller = more "live".
                           Rule of thumb: about 2 x the typical gap between data bursts (default 1.0).
    fps : int              Maximum animation frame rate in the browser (default 30).
    poll_ms : int          How often the browser fetches new samples from Python (default 200).
    title, y_title         Graph and y-axis titles.
    y_range : [lo, hi]     Fixed y-axis range; default None = smooth auto-range.
    colors : list          Line colours, one per channel.
    height : int           Graph height in pixels.
    max_points : int       Points kept per line in the browser, so memory stays bounded.
    """
    if id in _registered:
        raise ValueError(f"live_graph id {id!r} is already used")
    _registered.add(id)
    channels = list(channels or stream.channels)
    colors = colors or DEFAULT_COLORS
    gid, cfg, sink = f"{id}-graph", f"{id}-cfg", f"{id}-sink"
    route = f"_smoothdash/{id}"
    traces = [dict(type="scatter", mode="lines", name=c, x=[], y=[], line=dict(width=line_width,
                   color=colors[i % len(colors)]), hoverinfo="x+y+name") for i, c in enumerate(channels)]
    now = time.time()
    layout = dict(title=dict(text=title or "", x=0.01, font=dict(size=16)), height=height,
                  margin=dict(l=60, r=20, t=50 if title else 20, b=40), uirevision=id,
                  xaxis=dict(type="date", range=[(now - window_s - delay_s) * 1000, (now - delay_s) * 1000],
                             title=None, showgrid=True, gridcolor="#eee"),
                  yaxis=dict(title=dict(text=y_title or ""), range=y_range or [-1, 1], showgrid=True, gridcolor="#eee",
                             zeroline=False),
                  legend=dict(orientation="h", x=1, xanchor="right", y=1.02, yanchor="bottom"),
                  plot_bgcolor="white", paper_bgcolor="white")

    def _since():                               # JSON endpoint the browser polls
        try:
            cur = int(request.args.get("cursor", 0))
        except ValueError:
            cur = 0
        # a newly opened page only needs the last visible window, not the whole history
        restarted = cur > stream.seq          # Python side restarted: its sequence numbers began again at 0
        if restarted:
            cur = 0
        min_t = None if cur else time.time() - window_s - delay_s - 2
        new_cur, samples, reset = stream.since(cur, channels, min_t)
        return jsonify(server_now=time.time(), cursor=new_cur, samples=samples, reset=reset or restarted)

    app.server.add_url_rule("/" + route, endpoint=route, view_func=_since)
    app.clientside_callback(_JS, Output(sink, "children"), Input(cfg, "data"))

    config = dict(id=id, graph_id=gid, channels=channels, window=window_s, delay=delay_s, fps=fps,
                  poll_ms=poll_ms, max_points=max_points, y_range=y_range, line_width=line_width,
                  colors=[colors[i % len(colors)] for i in range(len(channels))],
                  url=app.config.requests_pathname_prefix + route)
    return html.Div([
        dcc.Graph(id=gid, figure=dict(data=traces, layout=layout),
                  config={"displayModeBar": False, "responsive": True}, style={"height": f"{height}px"}),
        dcc.Store(id=cfg, data=config),
        html.Div(id=sink, style={"display": "none"}),
    ], className="smoothdash")
