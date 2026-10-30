# Topics and messages (schema version 1)

Everything is JSON text (UTF-8) except the `status` topic, which is the plain word `online` or `offline`. `<prefix>` is `edge` and
`<device>` is `edge-1` unless you change them with `--prefix` and `--device`.

| Topic | When | QoS | Retained | Content |
|---|---|---|---|---|
| `<prefix>/<device>/mic` | one message per window the board prints (every 0.25 s) | 0 | no | the window's numbers, below |
| `<prefix>/<device>/status` | `online` when the bridge connects; `offline` when it stops cleanly **or** when the broker loses it (the last will) | 1 | yes | `online` / `offline` |
| `<prefix>/<device>/info` | once, when the board's start-up line is seen | 1 | yes | the firmware banner and its settings |
| `<prefix>/<device>/stats` | every `--stats-every` seconds and at a clean stop | 0 | no | what the bridge has counted |

## `mic` message

```json
{"v":1,"device":"edge-1","t":"2026-10-30T12:00:00.123+00:00","w":42,"mean":8440,"rms":145,"peak":700,"zcr":760,"hf":109,"clip":0,"rate_hz":7887}
```

| Field | Meaning |
|---|---|
| `v` | schema version (1). It changes if a field is added, removed or changes meaning |
| `device` | the device name from the topic |
| `t` | the PC's clock when the line was received, ISO 8601 UTC with milliseconds. **It is not the time of the sound**: the board has no real-time clock |
| `w` | window number since the board's last reset, counting from 1 |
| `mean`, `rms`, `peak`, `zcr`, `hf`, `clip` | the board's summary of 2000 ADC samples (0.25 s): resting level, loudness, biggest swing, mean crossings, how fast the signal changes, samples at 0 or 16383. Counts of a 14-bit ADC (0 to 16383) |
| `rate_hz` | the sample rate the board measured over that window (about 7880 when no samples were lost) |

All fields are required and all numbers are integers. A reader should ignore fields it does not know only if `v` is newer than it
understands; `edge_mqtt_bridge check` rejects unknown fields so that a change is noticed.

## What the bridge does with the board's lines

- Readable window lines are published once. A window number repeated straight after itself is dropped (Windows can hand over a stale
  buffer when a serial port is opened); a number that goes **backwards** is accepted and counted as a restart of the board.
- Unreadable lines are dropped and counted: `stale_lines` before the first good window, `bad_lines` after it.
- A window that is missing (the number jumps up) is not invented. The checker reports it.

## `stats` message

```json
{"v":1,"device":"edge-1","received":120,"accepted":118,"duplicates":2,"restarts":0,"stale_lines":4,"bad_lines":1,"publish_failures":0,"publish_rejected":0}
```

`received` counts readable window lines including repeats; `accepted` those passed on; `publish_failures` the publishes the MQTT
library refused, and `publish_rejected` the publishes the **broker** refused afterwards (for example, the bridge's user has no permission
for that topic). A rising `publish_rejected` means data is being lost. All counts are since the bridge started.
