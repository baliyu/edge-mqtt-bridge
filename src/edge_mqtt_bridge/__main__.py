"""Command line: python -m edge_mqtt_bridge run ...  |  python -m edge_mqtt_bridge check ..."""
from __future__ import annotations

import argparse
import signal
import sys
import time

from . import bridge as br
from .check import StreamChecker


def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(prog="edge_mqtt_bridge", description=__doc__)
    sub = ap.add_subparsers(dest="cmd", required=True)
    r = sub.add_parser("run", help="read the Edge's serial port and publish to MQTT")
    r.add_argument("--serial-port", required=True, help="for example COM4")
    r.add_argument("--baud", type=int, default=115200)
    r.add_argument("--device", default="edge-1", help="device name used in the topics")
    r.add_argument("--prefix", default="edge")
    r.add_argument("--mqtt-host", default="localhost")
    r.add_argument("--mqtt-port", type=int, default=1883)
    r.add_argument("--stats-every", type=float, default=10.0, help="seconds between stats messages")
    c = sub.add_parser("check", help="subscribe and check the messages against docs/PROTOCOL.md")
    c.add_argument("--device", default="+", help="device name, or + for all")
    c.add_argument("--prefix", default="edge")
    c.add_argument("--mqtt-host", default="localhost")
    c.add_argument("--mqtt-port", type=int, default=1883)
    c.add_argument("--count", type=int, default=40, help="stop after this many messages")
    c.add_argument("--timeout", type=float, default=30.0, help="stop after this many seconds")
    return ap


def cmd_run(a) -> int:
    try:
        import serial
    except ImportError:
        print("pyserial is missing: pip install pyserial", file=sys.stderr)
        return 2
    t = br.topics(a.prefix, a.device)
    pub = br.PahoPublisher(a.mqtt_host, a.mqtt_port, f"edge-mqtt-bridge-{a.device}", t["status"])
    try:
        pub.connect()
    except ConnectionError as e:
        print(e, file=sys.stderr)
        return 1
    try:
        ser = serial.Serial(a.serial_port, a.baud, timeout=0.5)
    except Exception as e:  # noqa: BLE001
        print(f"Could not open {a.serial_port}: {e}\nIs another program (PuTTY) using it?", file=sys.stderr)
        pub.close()
        return 2
    stop = {"now": False}
    signal.signal(signal.SIGINT, lambda *_: stop.__setitem__("now", True))
    print(f"Bridging {a.serial_port} to mqtt://{a.mqtt_host}:{a.mqtt_port}/{t['mic']}  (Ctrl+C to stop)", flush=True)
    ser.reset_input_buffer()
    bridge = br.Bridge(pub, device=a.device, prefix=a.prefix, stats_every=a.stats_every)
    with ser:
        bridge.run(ser, should_stop=lambda: stop["now"])
    time.sleep(0.2)          # let the last messages leave
    pub.close()
    c = bridge.filter.counters
    print(f"Stopped. windows accepted {c.accepted}, duplicates {c.duplicates}, restarts {c.restarts}, "
          f"stale {c.stale}, bad {c.bad}, publish failures {bridge.publish_failures}")
    return 0


def cmd_check(a) -> int:
    import paho.mqtt.client as mqtt
    checker, done = StreamChecker(), {"flag": False}
    client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, client_id="edge-mqtt-check")
    topic = f"{a.prefix}/{a.device}/mic"

    def on_connect(c, u, f, rc, p):
        c.subscribe(topic, qos=0)

    def on_message(c, u, msg):
        checker.feed(msg.payload.decode("utf-8", errors="replace"))
        if checker.count >= a.count:
            done["flag"] = True

    client.on_connect, client.on_message = on_connect, on_message
    try:
        client.connect(a.mqtt_host, a.mqtt_port, keepalive=30)
    except OSError as e:
        print(f"could not connect: {e}", file=sys.stderr)
        return 1
    client.loop_start()
    end = time.monotonic() + a.timeout
    while not done["flag"] and time.monotonic() < end:
        time.sleep(0.1)
    client.loop_stop()
    client.disconnect()
    print(f"Checked {checker.count} messages on {topic}; board restarts seen {checker.restarts}; problems {len(checker.problems)}")
    for p in checker.problems[:20]:
        print("  - " + p)
    return 0 if checker.count > 0 and not checker.problems else 1


def main(argv=None) -> int:
    a = build_parser().parse_args(argv)
    return cmd_run(a) if a.cmd == "run" else cmd_check(a)


if __name__ == "__main__":
    sys.exit(main())
