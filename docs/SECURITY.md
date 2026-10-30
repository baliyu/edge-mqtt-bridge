# Security: what is protected, how it was tested, and what is not

This is a small bridge, and this page is a statement of its limits as much as of its protections. Built with AI assistance (Claude).

## What the bridge and the broker configuration do

| Threat | What protects against it | How it is tested (against a real Mosquitto broker) |
|---|---|---|
| Someone connects without a password | `allow_anonymous false` | an anonymous client is refused |
| A guessed or wrong password | the broker's password file | a wrong password is refused, and the error text does not contain it |
| Someone publishes fake measurements for **another** device | the `bridge` user can **write only** `edge/edge-1/#` (`docs/mosquitto-acl.example`) | the broker drops a publish to `edge/other-device/mic`; the bridge is told and counts it in `publish_rejected` |
| A reader forges or changes data | the `reader` user can only **read** | a publish by the reader never reaches another subscriber |
| The password leaks through the command line or the shell history | the password is read from an environment variable only; there is **no** password argument, and argument abbreviation is switched off so `--mqtt-password` is an error | two tests; breaking either is caught |
| A silent permission mistake drops all data | the bridge speaks MQTT 5, so the broker says when it refuses a publish; the count shows in `stats` | the rejected publish is counted |
| A crashed bridge looks alive | the last will publishes `offline` (retained) | a test kills the connection and waits for `offline` |

The permission file that the tests load is the same file that is documented (`docs/mosquitto-acl.example`), so the two cannot drift apart.

## Things I learned from the tests

- Mosquitto's ACL file does **not** refuse a subscription to a topic you may not read: it accepts it and delivers nothing, with no error. The `check` command therefore says "no messages arrived" and names both possible causes (bridge not running, or no permission).
- A publish to a topic the user may not write is refused only in a way the client can see if the client speaks **MQTT 5**. With MQTT 3.1.1 the data would simply vanish. That is why the bridge uses version 5.
- Two clients with the same client ID disconnect each other. One of my own tests was vacuous for that reason until a deliberate-bug check exposed it.

## Not protected yet

- **No encryption.** Passwords and messages cross the network as plain text. Anyone who can see the traffic can read and change it. **Keep the broker on `127.0.0.1`** until TLS is added (next stage).
- **No per-message authenticity.** A host that holds the `bridge` password can publish anything under `edge/edge-1/`.
- **No rate limits or connection limits** are configured on the broker, so it is not hardened against a flood.
- **Shared secrets in a file.** The password reaches the process through an environment variable, so anything that can read that process's environment can read it. The broker's password file is hashed by `mosquitto_passwd`, and should be readable only by the broker's user.
- One device, one broker, no key rotation, no audit log.

## Setting it up (Ubuntu or WSL)

```
sudo mosquitto_passwd -c /etc/mosquitto/passwd bridge     # asks for a password: type it, do not put it in a command line
sudo mosquitto_passwd /etc/mosquitto/passwd reader
sudo cp docs/mosquitto-acl.example /etc/mosquitto/acl
sudo cp docs/mosquitto-secure.conf /etc/mosquitto/conf.d/edge.conf
sudo service mosquitto restart
```

Then run the bridge with the password in the environment (PowerShell shown; the characters you type are visible on screen):

```
$env:EDGE_MQTT_PASSWORD = Read-Host "bridge password"
py -m edge_mqtt_bridge run --serial-port COM4 --mqtt-user bridge
```

and the checker as the read-only user:

```
$env:EDGE_MQTT_PASSWORD = Read-Host "reader password"
py -m edge_mqtt_bridge check --mqtt-user reader
```
