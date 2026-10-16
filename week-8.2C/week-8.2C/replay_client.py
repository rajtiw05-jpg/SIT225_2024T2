"""
ReplayCloudClient - offline stand-in for arduino_iot_cloud.ArduinoCloudClient (same register/start API).

Replays my Week 8 phone recording (Arduino Cloud "Download historic data" export: accelerometer_x/y/z.csv,
2 samples per second) in real time, and imitates how cloud messages actually reach a Python device:
  * each message has a network delay (150 ms base + random jitter with a long tail),
  * every few seconds the connection stalls for 0.4-1.2 s and the queued messages then arrive in a burst,
  * messages keep their order (MQTT runs over TCP).
Used to test and record the smooth dashboard without the phone. The live run uses the real client.
"""
import csv
import os
import random
import time

MAP = {"acc_x": "accelerometer_x", "acc_y": "accelerometer_y", "acc_z": "accelerometer_z"}


class ReplayCloudClient:
    def __init__(self, device_id=None, username=None, password=None, export_dir="cloud_export", seed=8,
                 speed=1.0, **kw):
        self.callbacks, self.dir, self.rng, self.speed = {}, export_dir, random.Random(seed), speed

    def register(self, name, value=None, on_write=None, **kw):
        self.callbacks[name] = on_write

    def _load(self, name):
        with open(os.path.join(self.dir, MAP[name] + ".csv")) as f:
            return [float(r["value"]) for r in csv.DictReader(f)]

    def schedule(self, t0, period=0.5):
        """Yield (reading index, variable, time the phone took it, time it reaches Python), in delivery order."""
        last_delivery, stall_until = 0.0, 0.0
        next_stall = t0 + self.rng.uniform(4, 9)
        i = 0
        while True:
            gen = t0 + i * period                               # when the phone took reading i
            for j, k in enumerate(("acc_x", "acc_y", "acc_z")):
                sent = gen + j * 0.01
                deliver = sent + 0.15 + self.rng.lognormvariate(-2.6, 0.8)  # 150 ms + jitter (median ~75 ms)
                if sent >= next_stall:                          # connection stalls, messages queue up
                    stall_until = next_stall + self.rng.uniform(0.4, 1.2)
                    next_stall = stall_until + self.rng.uniform(4, 9)
                if deliver < stall_until:
                    deliver = stall_until + self.rng.uniform(0, 0.02)
                deliver = max(deliver, last_delivery)           # in-order delivery
                last_delivery = deliver
                yield i, k, sent, deliver
            i += 1

    def start(self):
        data = {k: self._load(k) for k in self.callbacks}
        n = min(len(v) for v in data.values())
        print(f"INFO - Connected to Arduino IoT cloud (replay of {n} readings per variable, looping).", flush=True)
        for i, k, sent, deliver in self.schedule(time.time() + 0.3, 0.5 / self.speed):
            if k not in self.callbacks:
                continue
            wait = deliver - time.time()
            if wait > 0:
                time.sleep(wait)
            self.callbacks[k](self, data[k][i % n])
