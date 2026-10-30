"""Command line: python -m edge_mqtt_bridge run ...  |  python -m edge_mqtt_bridge check ..."""
from __future__ import annotations

import argparse
import os
import signal
import sys
import time

from . import bridge as br
from .check import run_check


def resolve_credentials(user, env_name, environ=None):
    """(user, password) for the broker, or (None, None) when no user is given. The password comes from an environment variable and
    is never accepted on the command line, where it would show in the process list and the shell history."""
    environ = os.environ if environ is None else environ
    if not user:
        return None, None
    password = environ.get(env_name)
    if not password:
        raise SystemExit(f"--mqtt-user {user!r} needs its password in the environment variable {env_name}")
    return user, password


def add_broker_arguments(p) -> None:
    p.add_argument("--mqtt-host", default="localhost")
    p.add_argument("--mqtt-port", type=int, default=1883)
    p.add_argument("--mqtt-user", default=None, help="broker user name (the password is read from the environment)")
    p.add_argument("--mqtt-password-env", default="EDGE_MQTT_PASSWORD", help="name of the environment variable holding the password")


def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(prog="edge_mqtt_bridge", description=__doc__, allow_abbrev=False)
    sub = ap.add_subparsers(dest="cmd", required=True)
    r = sub.add_parser("run", help="read the Edge's serial port and publish to MQTT", allow_abbrev=False)
    r.add_argument("--serial-port", required=True, help="for example COM4")
    r.add_argument("--baud", type=int, default=115200)
    r.add_argument("--device", default="edge-1", help="device name used in the topics")
    r.add_argument("--prefix", default="edge")
    add_broker_arguments(r)
    r.add_argument("--stats-every", type=float, default=10.0, help="seconds between stats messages")
    c = sub.add_parser("check", help="subscribe and check the messages against docs/PROTOCOL.md", allow_abbrev=False)
    c.add_argument("--device", default="+", help="device name, or + for all")
    c.add_argument("--prefix", default="edge")
    add_broker_arguments(c)
    c.add_argument("--count", type=int, default=40, help="stop after this many messages")
    c.add_argument("--timeout", type=float, default=30.0, help="stop after this many seconds")
    return ap


def final_summary(bridge) -> str:
    """The one line printed when the bridge stops: what it accepted and dropped, and what the broker refused."""
    c = bridge.filter.counters
    return (f"Stopped. windows accepted {c.accepted}, duplicates {c.duplicates}, restarts {c.restarts}, stale {c.stale}, bad {c.bad}, "
            f"publish failures {bridge.publish_failures}, refused by the broker {getattr(bridge.pub, 'rejected', 0)}")


def cmd_run(a) -> int:
    try:
        import serial
    except ImportError:
        print("pyserial is missing: pip install pyserial", file=sys.stderr)
        return 2
    t = br.topics(a.prefix, a.device)
    user, password = resolve_credentials(a.mqtt_user, a.mqtt_password_env)
    pub = br.PahoPublisher(a.mqtt_host, a.mqtt_port, f"edge-mqtt-bridge-{a.device}", t["status"], username=user, password=password)
    try:
        pub.connect()
    except ConnectionError as e:
        print(e, file=sys.stderr)
        return 1
    if pub.status_accepted() is False:
        print(f"The broker refused the bridge's first message, so this user probably may not write {t['status']} (or anything under "
              f"{a.prefix}/{a.device}/). Nothing would reach the broker: stopping. Check the user, the --device name and the broker's permission file.",
              file=sys.stderr)
        pub.close()
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
    print(final_summary(bridge))
    return 0


def cmd_check(a) -> int:
    user, password = resolve_credentials(a.mqtt_user, a.mqtt_password_env)
    topic = f"{a.prefix}/{a.device}/mic"
    checker, error = run_check(a.mqtt_host, a.mqtt_port, topic, a.count, a.timeout, user, password)
    if error:
        print(error, file=sys.stderr)
        return 1
    if checker.count == 0:
        print(f"No messages arrived on {topic} within {a.timeout:.0f} s. Is the bridge running? A broker with an access list also "
              f"delivers nothing, without any error, to a user who has no permission to read the topic.", file=sys.stderr)
        return 1
    print(f"Checked {checker.count} messages on {topic}; board restarts seen {checker.restarts}; problems {len(checker.problems)}")
    for p in checker.problems[:20]:
        print("  - " + p)
    return 0 if checker.count > 0 and not checker.problems else 1


def main(argv=None) -> int:
    a = build_parser().parse_args(argv)
    return cmd_run(a) if a.cmd == "run" else cmd_check(a)


if __name__ == "__main__":
    sys.exit(main())
