"""
Measures what a viewer actually sees, in a real (headless Chromium) browser, for the Week 8 approach
(naive_dash.py, port 8051) and smoothdash (phone_smooth_dash.py, port 8050). Both apps must be running
with --replay. Writes browser_metrics.csv and fig_filmstrip.png.
"""
import asyncio
import json

import pandas as pd
from PIL import Image, ImageDraw, ImageFont
from playwright.async_api import async_playwright

SECONDS = 40
WATCH = """(gid) => {                         // records every change of the newest drawn point
  const host = document.getElementById(gid);
  window.__probe = {changes: [], ages: []};
  let last = null;
  setInterval(() => {
    const gd = host.classList.contains('js-plotly-plot') ? host : host.querySelector('.js-plotly-plot');
    if (!gd || !gd.data || !gd.data[0].x.length) return;
    const X = gd.data[0].x, newest = +new Date(X[X.length - 1]);
    if (newest !== last) { window.__probe.changes.push(performance.now()); last = newest; }
    window.__probe.ages.push(Date.now() - newest);
  }, 20);
}"""


async def measure(page, url, gid, name, shots):
    await page.goto(url)
    await page.wait_for_timeout(23000 if name == "naive" else 6000)    # naive needs N samples before its first graph
    await page.evaluate(WATCH, gid)
    if name == "smooth":
        await page.evaluate("""() => { for (const k in window.__smoothdash) { if (k.startsWith('__')) continue;
            const s = window.__smoothdash[k].stats; Object.assign(s, {frames: 0, frameGaps: [], late: 0, received: 0}); } }""")
    el = page.locator(f"#{gid}")
    frames = []
    for i in range(SECONDS * 2):
        if i < shots * 4 and i % 4 == 0:   # one screenshot every 2 s
            frames.append(await el.screenshot())
        await page.wait_for_timeout(500)
    p = await page.evaluate("() => window.__probe")
    ch = pd.Series(p["changes"]).diff().dropna() / 1000
    row = dict(method=name, data_updates_per_s=len(p["changes"]) / SECONDS,
               longest_wait_for_new_data_s=ch.max() if len(ch) else float("nan"),
               mean_age_of_newest_point_s=pd.Series(p["ages"]).mean() / 1000)
    if name == "smooth":
        s = await page.evaluate("() => window.__smoothdash['acc'].stats")
        g = pd.Series(s["frameGaps"])
        row.update(screen_updates_per_s=1000 / g.mean(), longest_frame_gap_ms=g.max(), p95_frame_gap_ms=g.quantile(.95),
                   samples_received=s["received"], samples_late_pct=100 * s["late"] / max(s["received"], 1))
    else:
        row.update(screen_updates_per_s=row["data_updates_per_s"],
                   longest_frame_gap_ms=row["longest_wait_for_new_data_s"] * 1000)
    return row, frames


async def main():
    async with async_playwright() as pw:
        b = await pw.chromium.launch()
        page = await b.new_page(viewport={"width": 1400, "height": 900})
        rows, strips = [], {}
        for name, url, gid in [("naive", "http://127.0.0.1:8051/", "g"), ("smooth", "http://127.0.0.1:8050/", "acc-graph")]:
            r, f = await measure(page, url, gid, name, shots=6)
            rows.append(r); strips[name] = f
        await b.close()
    df = pd.DataFrame(rows)
    df.to_csv("browser_metrics.csv", index=False)
    print(df.round(3).T.to_string())
    # filmstrip: the same graph every 2 s, naive (top) vs smooth (bottom), 2 x 2 frames each
    import io
    ims = {k: [Image.open(io.BytesIO(x)) for x in v][:4] for k, v in strips.items()}
    w = 900; h = int(w * ims["smooth"][0].height / ims["smooth"][0].width)
    lab, gap = 46, 30
    block = lab + 2 * (h + gap)
    sheet = Image.new("RGB", (2 * w + 30, 2 * block + 10), "white")
    d = ImageDraw.Draw(sheet)
    big = ImageFont.truetype("/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf", 32)
    small = ImageFont.truetype("/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf", 26)
    for r, k in enumerate(["naive", "smooth"]):
        y0 = r * block + 6
        d.text((10, y0), "Week 8 approach: new figure every N = 20 samples" if k == "naive"
               else "smoothdash: playout buffer + extendTraces + sliding axis", fill="black", font=big)
        for c, im in enumerate(ims[k]):
            x0 = 10 + (c % 2) * (w + 10); yy = y0 + lab + (c // 2) * (h + gap)
            sheet.paste(im.resize((w, h)), (x0, yy))
            d.rectangle([x0, yy, x0 + w - 1, yy + h - 1], outline="#bbb")
            d.text((x0 + w - 100, yy + h + 1), f"t = {2 * c} s", fill="#c00", font=small)
    sheet.save("fig_filmstrip.png")
    print("saved fig_filmstrip.png")

asyncio.run(main())
