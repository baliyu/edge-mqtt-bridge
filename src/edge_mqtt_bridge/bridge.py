"""The bridge: lines from the serial port in, MQTT messages out. See docs/PROTOCOL.md for the topics and the message format."""
from __future__ import annotations

import json
import time
from datetime import datetime, timezone
from typing import Callable, Optional, Protocol

from .parse import LineFilter

SCHEMA_VERSION = 1


class Publisher(Protocol):
    def publish(self, topic: str, payload: str, qos: int = 0, retain: bool = False) -> bool: ...


def topics(prefix: str, device: str) -> dict:
    base = f"{prefix}/{device}"
    return {"mic": f"{base}/mic", "status": f"{base}/status", "info": f"{base}/info", "stats": f"{base}/stats"}


def dumps(obj: dict) -> str:
    return json.dumps(obj, separators=(",", ":"), sort_keys=False)


class Bridge:
    """Feed it lines with handle_line(); it publishes through `publisher`. Time comes from injected clocks so tests are exact."""

    def __init__(self, publisher: Publisher, device: str = "edge-1", prefix: str = "edge", stats_every: float = 10.0,
                 clock: Callable[[], datetime] = lambda: datetime.now(timezone.utc),
                 monotonic: Callable[[], float] = time.monotonic):
        self.pub, self.device, self.t = publisher, device, topics(prefix, device)
        self.filter = LineFilter()
        self.stats_every, self._clock, self._mono = stats_every, clock, monotonic
        self._last_stats = monotonic()
        self.published = 0
        self.publish_failures = 0
        self.info_sent = False

    def _send(self, topic: str, payload: dict | str, qos: int = 0, retain: bool = False) -> None:
        text = payload if isinstance(payload, str) else dumps(payload)
        ok = self.pub.publish(topic, text, qos, retain)
        if ok:
            self.published += 1
        else:
            self.publish_failures += 1

    def start(self) -> None:
        if not getattr(self.pub, "announces_online", False):        # PahoPublisher already says 'online' when it connects
            self._send(self.t["status"], "online", qos=1, retain=True)

    def stop(self) -> None:
        self._send(self.t["status"], "offline", qos=1, retain=True)
        self._publish_stats()

    def handle_line(self, text: str) -> None:
        item = self.filter.feed(text)
        if item is not None:
            kind, value = item
            if kind == "meta":
                self._send(self.t["info"], {"v": SCHEMA_VERSION, "device": self.device, **value}, qos=1, retain=True)
                self.info_sent = True
            else:
                self._send(self.t["mic"], {"v": SCHEMA_VERSION, "device": self.device,
                                           "t": self._clock().isoformat(timespec="milliseconds"), **value})
        if self._mono() - self._last_stats >= self.stats_every:
            self._publish_stats()

    def _publish_stats(self) -> None:
        c = self.filter.counters
        self._send(self.t["stats"], {"v": SCHEMA_VERSION, "device": self.device, "received": c.received, "accepted": c.accepted,
                                     "duplicates": c.duplicates, "restarts": c.restarts, "stale_lines": c.stale,
                                     "bad_lines": c.bad, "publish_failures": self.publish_failures,
                                     "publish_rejected": getattr(self.pub, "rejected", 0)})
        self._last_stats = self._mono()

    def run(self, lines, should_stop: Callable[[], bool] = lambda: False) -> None:
        """Read lines from anything with readline() (a serial port, or a fake) until should_stop() or end of input."""
        self.start()
        try:
            while not should_stop():
                raw = lines.readline()
                if raw == b"" or raw == "":
                    if getattr(lines, "eof", False):
                        break
                    continue
                self.handle_line(raw.decode("ascii", errors="replace") if isinstance(raw, bytes) else raw)
        finally:
            self.stop()


class PahoPublisher:
    """A Publisher over paho-mqtt (version 2). Sets a last will ('offline', retained) so a crash is visible, and sends the 'online'
    message again after every reconnect."""

    announces_online = True          # it publishes 'online' itself on every (re)connect, so the Bridge need not

    def __init__(self, host: str, port: int, client_id: str, status_topic: str, username: Optional[str] = None,
                 password: Optional[str] = None):
        import paho.mqtt.client as mqtt
        self._mqtt = mqtt
        self.client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, client_id=client_id, protocol=mqtt.MQTTv5)   # v5: the broker then says when it refuses
        if username:
            self.client.username_pw_set(username, password)
        self.client.will_set(status_topic, "offline", qos=1, retain=True)
        self._status_topic = status_topic
        self.client.on_connect = self._on_connect
        self.client.on_publish = self._on_publish
        self.host, self.port = host, port
        self.connected = False
        self.last_reason = ""
        self.rejected = 0            # QoS 1 publishes the broker refused (QoS 0 publishes get no reply, so a refusal of those is invisible)
        self._online_mid = None      # the message id of the 'online' status message, to learn at once whether the broker accepted it
        self.online_accepted = None  # None until the broker has answered

    def _on_connect(self, client, userdata, flags, reason_code, properties):
        self.connected = not reason_code.is_failure
        self.last_reason = str(reason_code)
        if self.connected:
            self.online_accepted = None
            self._online_mid = client.publish(self._status_topic, "online", qos=1, retain=True).mid

    def _on_publish(self, client, userdata, mid, reason_code, properties):
        if reason_code.is_failure:
            self.rejected += 1
        if mid == self._online_mid:
            self.online_accepted = not reason_code.is_failure

    def status_accepted(self, timeout: float = 3.0):
        """True if the broker accepted the 'online' status message, False if it refused it (usually: this user may not write that
        topic), None if no answer came in time. A QoS 0 measurement message that is refused gets no reply at all, so this check is the
        way a wrong permission is noticed before data is silently dropped."""
        end = time.monotonic() + timeout
        while self.online_accepted is None and time.monotonic() < end:
            time.sleep(0.02)
        return self.online_accepted

    def connect(self, timeout: float = 10.0) -> None:
        self.client.connect(self.host, self.port, keepalive=30)
        self.client.loop_start()
        end = time.monotonic() + timeout
        while not self.connected and time.monotonic() < end:
            time.sleep(0.05)
        if not self.connected:
            why = f" ({self.last_reason})" if self.last_reason else ""
            self.client.loop_stop()
            raise ConnectionError(f"could not connect to MQTT broker at {self.host}:{self.port}{why}")

    def publish(self, topic: str, payload: str, qos: int = 0, retain: bool = False) -> bool:
        info = self.client.publish(topic, payload, qos=qos, retain=retain)
        return info.rc == self._mqtt.MQTT_ERR_SUCCESS

    def close(self) -> None:
        self.client.disconnect()
        self.client.loop_stop()
