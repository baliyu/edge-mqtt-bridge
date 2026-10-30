import json

from conftest import HEADER, FakePublisher, FakeSerial, line
from edge_mqtt_bridge.bridge import Bridge, topics


def make(pub, clock, **kw):
    return Bridge(pub, device="edge-1", clock=clock.now, monotonic=clock.monotonic, **kw)


def test_the_topics_are_prefix_device_name():
    assert topics("edge", "edge-1") == {"mic": "edge/edge-1/mic", "status": "edge/edge-1/status",
                                        "info": "edge/edge-1/info", "stats": "edge/edge-1/stats"}


def test_a_window_becomes_one_json_message_with_the_receive_time(pub, clock):
    b = make(pub, clock)
    b.handle_line(line(5, rms=150, clip=3))
    (m,) = pub.on("/mic")
    d = json.loads(m["payload"])
    assert d == {"v": 1, "device": "edge-1", "t": "2026-10-30T12:00:00.000+00:00", "w": 5, "mean": 8440, "rms": 150,
                 "peak": 700, "zcr": 760, "hf": 109, "clip": 3, "rate_hz": 7887}
    assert m["qos"] == 0 and m["retain"] is False


def test_status_is_online_then_offline_and_retained_with_qos_1(pub, clock):
    b = make(pub, clock)
    b.run(FakeSerial([HEADER, line(1)]))
    st = pub.on("/status")
    assert [m["payload"] for m in st] == ["online", "offline"]
    assert all(m["retain"] and m["qos"] == 1 for m in st)


def test_the_header_line_is_published_once_as_retained_info(pub, clock):
    b = make(pub, clock)
    b.run(FakeSerial([HEADER, line(1)]))
    (m,) = pub.on("/info")
    assert json.loads(m["payload"]) == {"v": 1, "device": "edge-1", "banner": "mic_logger v1", "window": 2000, "fs_target": 8000}
    assert m["retain"] and m["qos"] == 1


def test_bad_stale_and_repeated_lines_are_not_published(pub, clock):
    b = make(pub, clock)
    b.run(FakeSerial(["748,108,0,7888"] * 4 + [line(1), line(1), "garbage", line(2)]))
    assert [json.loads(m["payload"])["w"] for m in pub.on("/mic")] == [1, 2]
    stats = json.loads(pub.on("/stats")[-1]["payload"])
    assert stats["duplicates"] == 1 and stats["stale_lines"] == 4 and stats["bad_lines"] == 1 and stats["accepted"] == 2


def test_stats_are_sent_on_the_interval_and_at_stop(pub, clock):
    b = make(pub, clock, stats_every=10.0)
    b.handle_line(line(1))
    assert pub.on("/stats") == []
    clock.mono = 10.5
    b.handle_line(line(2))
    assert len(pub.on("/stats")) == 1
    b.stop()
    assert len(pub.on("/stats")) == 2


def test_failed_publishes_are_counted_and_do_not_stop_the_bridge(clock):
    pub = FakePublisher(fail=True)
    b = make(pub, clock)
    b.run(FakeSerial([line(1), line(2)]))
    assert b.publish_failures >= 2 and b.published == 0
    assert len(pub.sent) >= 2


def test_stop_publishes_offline_even_if_reading_fails(pub, clock):
    class Broken:
        def readline(self):
            raise OSError("port vanished")
    b = make(pub, clock)
    try:
        b.run(Broken())
    except OSError:
        pass
    assert pub.on("/status")[-1]["payload"] == "offline"


def test_the_bridge_says_online_unless_the_publisher_already_does(clock):
    class Announcing(FakePublisher):
        announces_online = True
    quiet, plain = Announcing(), FakePublisher()
    for pub in (quiet, plain):
        make(pub, clock).start()
    assert quiet.on("/status") == []
    assert [m["payload"] for m in plain.on("/status")] == ["online"]


def test_refused_publishes_are_reported_in_the_stats_when_the_publisher_counts_them(clock):
    class Counting(FakePublisher):
        rejected = 3
    pub = Counting()
    b = make(pub, clock)
    b.stop()
    assert json.loads(pub.on("/stats")[-1]["payload"])["publish_rejected"] == 3
    plain = FakePublisher()
    make(plain, clock).stop()
    assert json.loads(plain.on("/stats")[-1]["payload"])["publish_rejected"] == 0
