import json
from datetime import datetime, timezone

import pytest


def line(w, rate=7887, **kw):
    d = dict(mean=8440, rms=145, peak=700, zcr=760, hf=109, clip=0)
    d.update(kw)
    return f"{w},{d['mean']},{d['rms']},{d['peak']},{d['zcr']},{d['hf']},{d['clip']},{rate}"


HEADER = "# mic_logger v1 fs_target=8000 window=2000 block=100 pin=29 adc=SE1 ref=2p0 avg=1 bits=14"


class FakePublisher:
    def __init__(self, fail=False):
        self.sent, self.fail = [], fail

    def publish(self, topic, payload, qos=0, retain=False):
        self.sent.append({"topic": topic, "payload": payload, "qos": qos, "retain": retain})
        return not self.fail

    def on(self, suffix):
        return [m for m in self.sent if m["topic"].endswith(suffix)]


class FakeSerial:
    """Gives out its lines one by one, then reports end of input."""
    def __init__(self, lines):
        self.q = [ln + "\r\n" for ln in lines]
        self.eof = False

    def readline(self):
        if self.q:
            return self.q.pop(0).encode()
        self.eof = True
        return b""


class Clock:
    def __init__(self):
        self.mono = 0.0

    def now(self):
        return datetime(2026, 10, 30, 12, 0, 0, tzinfo=timezone.utc)

    def monotonic(self):
        return self.mono


@pytest.fixture
def pub():
    return FakePublisher()


@pytest.fixture
def clock():
    return Clock()
