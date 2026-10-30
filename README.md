# edge-mqtt-bridge

[![CI](https://github.com/baliyu/edge-mqtt-bridge/actions/workflows/ci.yml/badge.svg)](https://github.com/baliyu/edge-mqtt-bridge/actions/workflows/ci.yml)

A small, tested bridge from a serial port to an MQTT broker. It reads the one-line-per-window output of the SparkFun Edge's microphone
logger (from my [tinyml-edge-lab](https://github.com/baliyu/tinyml-edge-lab) repository), checks each line, and publishes it as a JSON message with an
online/offline status, a retained info message and periodic counters. A second command subscribes and checks that what arrives matches
the documented format. The topics and the message format are in [docs/PROTOCOL.md](docs/PROTOCOL.md).

Built with AI assistance (Claude). I chose the design, ran it on my own hardware and checked the results; the code and tests were written with Claude.

## Status, stated plainly

- Tested with a fake serial port and a fake MQTT client, and against a **real Mosquitto broker** (the integration tests start one on a private port and are skipped if Mosquitto is not installed). CI runs both.
- The tests were checked by breaking the code on purpose: 12 deliberate bugs in the bridge and 8 in the security behaviour, each caught. One of my own security tests turned out to be vacuous (two clients shared an ID) until that check exposed it; it is fixed.
- Run against a real board: yes, in four short runs (below). They show it works; they are not a long-run test.
- **Users, passwords and per-topic permissions are supported and tested against a real broker** (see [docs/SECURITY.md](docs/SECURITY.md)): the bridge user can write only its own device's topics, a reader can only read, and at start-up the bridge stops with a clear error if the broker refuses its first message.
- **No TLS yet.** Passwords and messages cross the network as plain text, so keep the broker on `127.0.0.1` until TLS is added (the next step, below).
- One device, one message format. No cloud, no database, no dashboard.

## Quick start

```
pip install -e .[dev]
pytest -q
```

A local broker (Ubuntu or WSL): `sudo apt install mosquitto mosquitto-clients`. Then, with the Edge on a serial port:

```
python -m edge_mqtt_bridge run --serial-port COM4            # Windows; /dev/ttyUSB0 on Linux. With broker users: add --mqtt-user bridge, and put the password in the EDGE_MQTT_PASSWORD environment variable (never on the command line)
python -m edge_mqtt_bridge check --count 40                  # in another window: subscribe and check the format
mosquitto_sub -t "edge/#" -v                                 # or just watch the messages
```

Stop the bridge with Ctrl+C: it publishes `offline` (retained) before it exits. If it is killed instead, the broker publishes `offline` itself (the MQTT last will; there is a test for that).

## Run on a real board

One SparkFun Edge running the mic_logger firmware, on a Windows 11 laptop; the broker was Mosquitto 2.0.18 in WSL2 on the same laptop, reached from the bridge on Windows as `localhost`. Four short runs on 30 October 2026:

| Run | What happened |
|---|---|
| 1 | 69 windows read and published; 0 duplicates, 0 restarts, 0 stale or bad lines, 0 publish failures. `status` went `online`, then `offline` (retained) after Ctrl+C. The 69 messages arrived about 0.254 s apart on average, which is the board's own window rate (2000 samples at about 7878 Hz), so the bridge showed no visible delay in the stream |
| 2 | The bridge accepted 159 windows (1 stale line dropped: the bytes Windows hands over when a port is opened; 0 bad lines, 0 publish failures). `check` read 81 of the messages in another window and found 0 problems and 0 board restarts |
| 3 | The same laptop with the broker secured (users `bridge` and `reader`, the permission file in `docs/`). An anonymous publish was refused ("not authorised", exit code 5). The bridge, as `bridge`, accepted 91 windows with 0 publish failures; `check`, as the read-only `reader`, read 41 messages and found 0 problems. The passwords used in this run were short, which is acceptable only because the broker listens on `127.0.0.1` |
| 4 | Three refusal tests on the secured broker. No password: refused ("Not authorized"). A wrong password: refused, and the message did not contain it. The bridge run as another device (`--device other-device`): it connected and read 132 windows, but the broker refused only the two QoS 1 status messages; the QoS 0 measurements were dropped silently and the bridge could not tell. That gap was found by this run, and the bridge now checks its first message and stops (see `docs/SECURITY.md`). The serial port also handed over a stale block of 2,384 repeated lines, which the filter dropped |

Not measured: end-to-end latency, behaviour over hours, behaviour when the broker is stopped or restarted mid-run, or a second device.

## What is where

| Path | What it is |
|---|---|
| `src/edge_mqtt_bridge/parse.py` | Which serial lines are real windows: stale bytes, repeats, restarts, impossible values |
| `src/edge_mqtt_bridge/bridge.py` | The bridge and the paho-mqtt publisher (last will, online message after every reconnect) |
| `src/edge_mqtt_bridge/check.py` | The message checker (format, repeats, gaps, restarts) |
| `docs/PROTOCOL.md` | Topics, QoS, retained flags and every field |
| `docs/SECURITY.md` | What is protected, how it is tested, what is not; how to set up users and permissions |
| `docs/mosquitto-acl.example`, `docs/mosquitto-secure.conf` | The permission file (the tests load this very file) and a broker configuration |
| `tests/` | Unit tests with fakes, and integration tests against a real broker |

## Limits

- The message time `t` is the PC's clock at receipt, not the time of the sound.
- Messages published while the broker is unreachable are not queued by this program. `publish_failures` counts them.
- Only the microphone logger's line format is understood.

## Next

1. TLS (a certificate authority, a server certificate, and a client that checks it), tested the same way.
2. A second device and a second line format (the gesture demo).
3. Measured latency and message rate on a real board.

## Licence

MIT.
