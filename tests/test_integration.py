"""Against a real Mosquitto broker on a private port. Skipped when mosquitto is not installed."""
import json
import shutil
import socket
import subprocess
import time

import pytest

from conftest import HEADER, FakeSerial, line
from edge_mqtt_bridge.bridge import Bridge, PahoPublisher, topics
from edge_mqtt_bridge.check import StreamChecker

pytestmark = pytest.mark.skipif(shutil.which("mosquitto") is None, reason="mosquitto is not installed")


@pytest.fixture
def broker(tmp_path):
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        port = s.getsockname()[1]
    conf = tmp_path / "mosquitto.conf"
    conf.write_text(f"listener {port} 127.0.0.1\nallow_anonymous true\npersistence false\n")
    proc = subprocess.Popen(["mosquitto", "-c", str(conf)], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    for _ in range(50):
        try:
            socket.create_connection(("127.0.0.1", port), timeout=0.2).close()
            break
        except OSError:
            time.sleep(0.1)
    yield port
    proc.terminate()
    proc.wait(timeout=5)


def subscriber(port, topic_filter):
    import paho.mqtt.client as mqtt
    got = []
    c = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, client_id="test-sub")
    c.on_connect = lambda cl, u, f, rc, p: cl.subscribe(topic_filter, qos=1)
    c.on_message = lambda cl, u, m: got.append((m.topic, m.payload.decode(), m.retain))
    c.connect("127.0.0.1", port)
    c.loop_start()
    return c, got


def wait_for(cond, seconds=5.0):
    end = time.monotonic() + seconds
    while time.monotonic() < end:
        if cond():
            return True
        time.sleep(0.05)
    return False


def test_messages_reach_a_real_broker_and_pass_the_checker(broker):
    t = topics("edge", "edge-1")
    sub, got = subscriber(broker, "edge/#")
    pub = PahoPublisher("127.0.0.1", broker, "bridge-test", t["status"])
    pub.connect()
    Bridge(pub).run(FakeSerial([HEADER] + [line(w) for w in range(1, 21)]))
    assert wait_for(lambda: sum(1 for g in got if g[0].endswith("/mic")) == 20)
    checker = StreamChecker()
    for topic, payload, _ in got:
        if topic.endswith("/mic"):
            checker.feed(payload)
    assert checker.count == 20 and checker.problems == []
    assert wait_for(lambda: any(g[0].endswith("/status") and g[1] == "offline" for g in got))
    assert [g[1] for g in got if g[0].endswith("/status")] == ["online", "offline"]      # one 'online', not two
    pub.close()
    sub.loop_stop()
    sub.disconnect()


def test_a_crashed_bridge_is_shown_offline_by_the_last_will(broker):
    t = topics("edge", "edge-1")
    sub, got = subscriber(broker, "edge/+/status")
    pub = PahoPublisher("127.0.0.1", broker, "bridge-crash", t["status"])
    pub.connect()
    assert wait_for(lambda: any(g[1] == "online" for g in got))
    pub.client._sock.close()                       # the connection dies without a clean disconnect
    assert wait_for(lambda: any(g[1] == "offline" for g in got), seconds=10)
    pub.client.loop_stop()
    sub.loop_stop()
    sub.disconnect()
