"""A real Mosquitto broker with a password file and the ACL in docs/mosquitto-acl.example. Skipped when mosquitto is not installed."""
import itertools
import os
import shutil
import socket
import subprocess
import time
from pathlib import Path

import pytest

from conftest import FakeSerial, line
from edge_mqtt_bridge.bridge import Bridge, PahoPublisher, topics
from edge_mqtt_bridge.check import run_check

pytestmark = pytest.mark.skipif(shutil.which("mosquitto") is None or shutil.which("mosquitto_passwd") is None,
                                reason="mosquitto is not installed")
ACL = Path(__file__).resolve().parents[1] / "docs" / "mosquitto-acl.example"
USERS = {"bridge": "bridge-pw-1", "reader": "reader-pw-2"}
_ids = itertools.count()          # every test client needs its own ID: a second client with the same ID disconnects the first


@pytest.fixture
def broker(tmp_path):
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        port = s.getsockname()[1]
    pw = tmp_path / "passwd"
    for i, (u, p) in enumerate(USERS.items()):
        subprocess.run(["mosquitto_passwd", "-b"] + (["-c"] if i == 0 else []) + [str(pw), u, p], check=True, capture_output=True)
    conf = tmp_path / "mosquitto.conf"
    run_as = "user root\n" if os.geteuid() == 0 else ""        # as root Mosquitto drops to its own user and could not read the files below
    conf.write_text(f"{run_as}listener {port} 127.0.0.1\nallow_anonymous false\npassword_file {pw}\nacl_file {ACL}\npersistence false\n")
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


def wait_for(cond, seconds=5.0):
    end = time.monotonic() + seconds
    while time.monotonic() < end:
        if cond():
            return True
        time.sleep(0.05)
    return False


def listener(port, user, pw, filt="edge/#"):
    import paho.mqtt.client as mqtt
    got = []
    c = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, client_id=f"test-{user}-{next(_ids)}")
    c.username_pw_set(user, pw)
    c.on_connect = lambda cl, u, f, rc, p: cl.subscribe(filt, qos=1)
    c.on_message = lambda cl, u, m: got.append((m.topic, m.payload.decode()))
    c.connect("127.0.0.1", port)
    c.loop_start()
    return c, got


def try_publisher(port, user, pw):
    p = PahoPublisher("127.0.0.1", port, "bridge-t", topics("edge", "edge-1")["status"], username=user, password=pw)
    try:
        p.connect(timeout=3)
    except ConnectionError as e:
        return None, str(e)
    return p, ""


def test_a_client_without_a_password_is_refused(broker):
    p, why = try_publisher(broker, None, None)
    assert p is None and "Not authorized" in why or "not authorized" in why.lower()


def test_a_wrong_password_is_refused_and_the_message_does_not_contain_it(broker):
    p, why = try_publisher(broker, "bridge", "wrong-password")
    assert p is None and "wrong-password" not in why


def test_the_bridge_user_can_publish_and_the_reader_user_can_check_the_stream(broker):
    p, why = try_publisher(broker, "bridge", USERS["bridge"])
    assert p is not None, why
    import threading
    out = {}
    th = threading.Thread(target=lambda: out.update(r=run_check("127.0.0.1", broker, "edge/+/mic", 15, 10, "reader", USERS["reader"])))
    th.start()
    time.sleep(1.0)
    Bridge(p).run(FakeSerial([line(w) for w in range(1, 16)]))
    th.join()
    checker, error = out["r"]
    assert error is None and checker.count == 15 and checker.problems == []
    p.close()


def test_the_bridge_cannot_publish_to_another_devices_topics(broker):
    sub, got = listener(broker, "reader", USERS["reader"], "edge/#")
    time.sleep(0.5)
    p, why = try_publisher(broker, "bridge", USERS["bridge"])
    assert p is not None, why
    p.publish("edge/other-device/mic", '{"spoofed":true}', qos=1)        # not allowed by the ACL: dropped by the broker
    p.publish("edge/edge-1/mic", '{"v":1}', qos=1)                       # allowed
    assert wait_for(lambda: any(t == "edge/edge-1/mic" for t, _ in got))
    assert wait_for(lambda: p.rejected == 1)                          # and the bridge is told: the stats will show it
    assert not any(t == "edge/other-device/mic" for t, _ in got)
    p.close()
    sub.loop_stop()
    sub.disconnect()


def test_the_reader_cannot_publish(broker):
    sub, got = listener(broker, "reader", USERS["reader"], "edge/#")
    time.sleep(0.5)
    pub, got2 = listener(broker, "reader", USERS["reader"], "nothing/#")     # a second reader that tries to publish
    time.sleep(0.5)
    p, why = try_publisher(broker, "bridge", USERS["bridge"])
    assert p is not None, why
    p.publish("edge/edge-1/mic", '{"genuine":true}', qos=1)
    assert wait_for(lambda: any("genuine" in payload for _, payload in got))      # the listener really listens
    pub.publish("edge/edge-1/mic", '{"forged":true}', qos=1)
    time.sleep(1.0)
    assert not any("forged" in payload for _, payload in got)
    p.close()
    for c in (sub, pub):
        c.loop_stop()
        c.disconnect()


def test_a_topic_the_user_may_not_read_just_stays_silent_and_the_check_command_says_what_that_can_mean(broker, monkeypatch, capsys):
    # Mosquitto's ACL file accepts such a subscription and then never delivers anything to it: no error is raised anywhere.
    checker, error = run_check("127.0.0.1", broker, "secret/#", 3, 2, "reader", USERS["reader"])
    assert checker.count == 0 and error is None
    from edge_mqtt_bridge.__main__ import main
    monkeypatch.setenv("EDGE_MQTT_PASSWORD", USERS["reader"])
    code = main(["check", "--mqtt-host", "127.0.0.1", "--mqtt-port", str(broker), "--mqtt-user", "reader", "--device", "nobody",
                 "--count", "3", "--timeout", "2"])
    err = capsys.readouterr().err
    assert code == 1 and "No messages arrived" in err and "no permission" in err and USERS["reader"] not in err


def test_the_checker_says_when_the_broker_refuses_its_password(broker):
    checker, error = run_check("127.0.0.1", broker, "edge/+/mic", 5, 5, "reader", "wrong")
    assert error is not None and "refused the connection" in error
