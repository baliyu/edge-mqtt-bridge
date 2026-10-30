import json

from conftest import FakePublisher, FakeSerial, line
from edge_mqtt_bridge.bridge import Bridge
from edge_mqtt_bridge.check import StreamChecker, validate_payload


def msg(**kw):
    d = {"v": 1, "device": "edge-1", "t": "2026-10-30T12:00:00.000+00:00", "w": 1, "mean": 8440, "rms": 145, "peak": 700,
         "zcr": 760, "hf": 109, "clip": 0, "rate_hz": 7887}
    d.update(kw)
    return json.dumps(d)


def test_a_good_message_has_no_problems():
    assert validate_payload(msg()) == []


def test_each_kind_of_bad_message_is_reported():
    assert validate_payload("not json") == ["not valid JSON"]
    assert "missing field rms" in validate_payload(json.dumps({k: v for k, v in json.loads(msg()).items() if k != "rms"}))
    assert "field w has the wrong type" in validate_payload(msg(w="1"))
    assert "field w has the wrong type" in validate_payload(msg(w=True))
    assert "unknown field extra" in validate_payload(msg(extra=1))
    assert "unsupported schema version" in validate_payload(msg(v=2))
    assert "peak is larger than a 14-bit count" in validate_payload(msg(peak=20000))


def test_the_stream_checker_notices_repeats_gaps_and_restarts():
    c = StreamChecker()
    for w in (1, 2, 2, 5, 6, 1):
        c.feed(msg(w=w))
    assert c.restarts == 1
    joined = " ".join(c.problems)
    assert "window 2 repeated" in joined and "windows 3 to 4 did not arrive" in joined


def test_what_the_bridge_publishes_passes_the_checker(clock):
    pub = FakePublisher()
    Bridge(pub, clock=clock.now, monotonic=clock.monotonic).run(FakeSerial([line(w) for w in range(1, 30)]))
    c = StreamChecker()
    for m in pub.on("/mic"):
        c.feed(m["payload"])
    assert c.count == 29 and c.problems == []
