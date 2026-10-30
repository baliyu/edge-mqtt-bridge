"""A checker: subscribe to the bridge's messages and say whether they match docs/PROTOCOL.md."""
from __future__ import annotations

import json

REQUIRED = {"v": int, "device": str, "t": str, "w": int, "mean": int, "rms": int, "peak": int, "zcr": int, "hf": int,
            "clip": int, "rate_hz": int}


def validate_payload(text: str) -> list[str]:
    """Problems with one message on the mic topic; an empty list means it matches the format."""
    try:
        d = json.loads(text)
    except ValueError:
        return ["not valid JSON"]
    if not isinstance(d, dict):
        return ["not a JSON object"]
    out = [f"missing field {k}" for k in REQUIRED if k not in d]
    out += [f"field {k} has the wrong type" for k, typ in REQUIRED.items() if k in d and (not isinstance(d[k], typ) or isinstance(d[k], bool))]
    out += [f"unknown field {k}" for k in d if k not in REQUIRED]
    if d.get("v") != 1:
        out.append("unsupported schema version")
    if isinstance(d.get("peak"), int) and d["peak"] > 16383:
        out.append("peak is larger than a 14-bit count")
    return out


class StreamChecker:
    """Checks a stream of messages per device: each valid, and the window number rising (a drop means a board restart)."""

    def __init__(self):
        self.count = 0
        self.problems: list[str] = []
        self.restarts = 0
        self._last: dict[str, int] = {}

    def feed(self, text: str) -> None:
        self.count += 1
        for p in validate_payload(text):
            self.problems.append(f"message {self.count}: {p}")
        try:
            d = json.loads(text)
            dev, w = d["device"], d["w"]
        except (ValueError, KeyError, TypeError):
            return
        last = self._last.get(dev)
        if last is not None:
            if w == last:
                self.problems.append(f"message {self.count}: window {w} repeated")
            elif w < last:
                self.restarts += 1
            elif w > last + 1:
                self.problems.append(f"message {self.count}: windows {last + 1} to {w - 1} did not arrive")
        self._last[dev] = w


def run_check(host: str, port: int, topic: str, count: int, timeout: float, username=None, password=None):
    """Subscribe to `topic` and check up to `count` messages. Returns (StreamChecker, error), where error is None, or says why
    nothing could be checked (refused connection, refused subscription, no broker)."""
    import time

    import paho.mqtt.client as mqtt
    checker, state = StreamChecker(), {"done": False, "error": None}
    client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, client_id="edge-mqtt-check", protocol=mqtt.MQTTv5)
    if username:
        client.username_pw_set(username, password)

    def on_connect(c, u, f, rc, p):
        if rc.is_failure:
            state["error"], state["done"] = f"the broker refused the connection ({rc})", True
        else:
            c.subscribe(topic, qos=0)

    def on_subscribe(c, u, mid, reason_codes, p):
        if any(r.is_failure for r in reason_codes):
            state["error"], state["done"] = f"the broker refused the subscription to {topic}", True

    def on_message(c, u, msg):
        checker.feed(msg.payload.decode("utf-8", errors="replace"))
        if checker.count >= count:
            state["done"] = True

    client.on_connect, client.on_subscribe, client.on_message = on_connect, on_subscribe, on_message
    try:
        client.connect(host, port, keepalive=30)
    except OSError as e:
        return checker, f"could not connect: {e}"
    client.loop_start()
    end = time.monotonic() + timeout
    while not state["done"] and time.monotonic() < end:
        time.sleep(0.05)
    client.loop_stop()
    client.disconnect()
    return checker, state["error"]
