# Security: what is protected, how it was tested, and what is not

This is a small bridge, and this page is a statement of its limits as much as of its protections. Built with AI assistance (Claude).

## What the bridge and the broker configuration do

| Threat | What protects against it | How it is tested (against a real Mosquitto broker) |
|---|---|---|
| Someone connects without a password | `allow_anonymous false` | an anonymous client is refused |
| A guessed or wrong password | the broker's password file | a wrong password is refused, and the error text does not contain it |
| Someone publishes fake measurements for **another** device | the `bridge` user can **write only** `edge/edge-1/#` (`docs/mosquitto-acl.example`) | the broker drops a publish to `edge/other-device/mic`, and refuses the QoS 1 status message, which the bridge notices at start-up |
| A reader forges or changes data | the `reader` user can only **read** | a publish by the reader never reaches another subscriber |
| The password leaks through the command line or the shell history | the password is read from an environment variable only; there is **no** password argument, and argument abbreviation is switched off so `--mqtt-password` is an error | two tests; breaking either is caught |
| A wrong permission makes the bridge look healthy while nothing arrives | at start-up the bridge checks that the broker accepted its first (QoS 1) message, and stops with a clear error if not. **Limit:** afterwards, refused QoS 0 measurements get no reply and are dropped silently; `publish_rejected` counts only refused QoS 1 messages | an integration test (refused for another device, accepted for its own); the QoS 0 limit has its own test; and it was seen on the real broker (below) |
| Someone reads or alters the traffic on the network | **TLS (optional, `--mqtt-tls-ca`):** the bridge checks the broker's certificate, checks that its name matches, trusts **only** the authority file you name (not the system's list), and refuses anything older than TLS 1.2 | a real broker with certificates made by `docs/make-certs.sh`: the connection uses TLS 1.2 or newer (read from the live socket); an untrusted authority, a certificate for another hostname and a plain client on the TLS port are each refused; users and permissions still apply over TLS |
| A password sent in the clear to another machine by mistake | the bridge warns when a password would travel without TLS to any host except localhost | a unit test |
| A crashed bridge looks alive | the last will publishes `offline` (retained) | a test kills the connection and waits for `offline` |

The permission file that the tests load is the same file that is documented (`docs/mosquitto-acl.example`), so the two cannot drift apart.

## Things I learned from the tests

- Mosquitto's ACL file does **not** refuse a subscription to a topic you may not read: it accepts it and delivers nothing, with no error. The `check` command therefore says "no messages arrived" and names both possible causes (bridge not running, or no permission).
- A publish to a topic the user may not write is reported to the client only if the client speaks **MQTT 5 and the publish is QoS 1 or 2**. A QoS 0 publish gets no reply in any version, so the broker can drop it and the client can never know.
- **Found on the real broker, not by the automated tests.** Run as `--device other-device`, the bridge read 132 windows and was told about 2 refusals (the two QoS 1 status messages); about 130 measurements were dropped silently, and it ran for 33 seconds looking healthy. The start-up check was added because of this.
- **Found on the real laptop, not by the tests.** The first certificate authority my script made did not declare that it may sign certificates (no key-usage extension). Python 3.13 checks that strictly by default and refused it with "CA cert does not include key usage extension"; Python 3.12, which my tests and CI used, does not. The script is fixed (and prints what it declares), the client now sets the strict flag itself on every Python version, and CI runs 3.12 and 3.13.
- A checker that is not given the authority file for a TLS port connects at the network level but never gets an MQTT session. My first version then said "no messages arrived: is the bridge running?", which blames the wrong thing. A test caught it; it now says it never got a session and suggests `--mqtt-tls-ca`.
- On the same run the serial port handed over a stale block of 2,384 identical lines; the line filter dropped all of them (`duplicates 2384`), so nothing would have been published twice.
- Two clients with the same client ID disconnect each other. One of my own tests was vacuous for that reason until a deliberate-bug check exposed it.

## Not protected yet

- **TLS is optional and one-sided.** Without `--mqtt-tls-ca` nothing is encrypted, so keep the broker on `127.0.0.1` in that case. With it, the bridge verifies the broker, but the broker does not verify the bridge by certificate: a password is still the only client credential (no mutual TLS).
- **Certificates.** The sample certificates are private ones for `localhost`. The authority's private key (`ca.key`) can sign a certificate for anything the bridge trusts, so it must stay off the broker and out of git. Certificates expire (365 days by default) and there is no revocation. The sample broker configuration does not restrict which TLS versions the broker accepts; the bridge refuses anything older than 1.2 on its side.
- **No per-message authenticity.** A host that holds the `bridge` password can publish anything under `edge/edge-1/`.
- **No rate limits or connection limits** are configured on the broker, so it is not hardened against a flood.
- **Shared secrets in a file.** The password reaches the process through an environment variable, so anything that can read that process's environment can read it. The broker's password file is hashed by `mosquitto_passwd`, and should be readable only by the broker's user.
- One device, one broker, no key rotation, no audit log.

## Setting it up (Ubuntu or WSL)

```
sudo mosquitto_passwd -c /etc/mosquitto/passwd bridge     # asks for a password: type it, do not put it in a command line
sudo mosquitto_passwd /etc/mosquitto/passwd reader
sudo chown root:mosquitto /etc/mosquitto/passwd           # the broker runs as the mosquitto user and must be able to read it
sudo chmod 640 /etc/mosquitto/passwd
sudo cp docs/mosquitto-acl.example /etc/mosquitto/acl
sudo chmod 644 /etc/mosquitto/acl                         # a file copied from a Windows drive arrives executable
sudo cp docs/mosquitto-secure.conf /etc/mosquitto/conf.d/edge.conf
sudo service mosquitto restart
systemctl is-active mosquitto                             # must say "active"
mosquitto_pub -t edge/edge-1/mic -m test; echo $?         # must be refused ("not authorised", exit code 5)
```

If the broker will not start, `sudo tail /var/log/mosquitto/mosquitto.log` says why. The commonest cause is a password file the broker's user cannot
read ("Unable to open pwfile"). With Mosquitto 2.0.18 the group must be `mosquitto`; `mosquitto_passwd` warns that future versions may want
`root:root` instead, so follow the warning your version prints.

Then run the bridge with the password in the environment. This PowerShell prompt shows nothing while you type:

```
$s = Read-Host "bridge password" -AsSecureString
$env:EDGE_MQTT_PASSWORD = [Runtime.InteropServices.Marshal]::PtrToStringAuto([Runtime.InteropServices.Marshal]::SecureStringToBSTR($s))
py -m edge_mqtt_bridge run --serial-port COM4 --mqtt-user bridge
```

and, in another window, the checker as the read-only user (set `EDGE_MQTT_PASSWORD` to the reader's password the same way):

```
py -m edge_mqtt_bridge check --mqtt-user reader
```

Choose passwords of 12 or more random characters. The first test run of this setup used short ones, which is acceptable only because the broker listens on `127.0.0.1`.

## Turning TLS on (Ubuntu or WSL for the broker; the bridge can run anywhere that can read `ca.crt`)

```
bash docs/make-certs.sh certs                                   # ca.crt, server.crt, server.key, ca.key in ./certs
sudo mkdir -p /etc/mosquitto/certs
sudo cp certs/ca.crt certs/server.crt certs/server.key /etc/mosquitto/certs/       # NOT ca.key
sudo chown root:mosquitto /etc/mosquitto/certs/server.key && sudo chmod 640 /etc/mosquitto/certs/server.key
sudo cp docs/mosquitto-tls.conf /etc/mosquitto/conf.d/edge.conf                      # replaces the plain-text listener
sudo service mosquitto restart && systemctl is-active mosquitto
```

Copy only `ca.crt` to the machine that runs the bridge (the authority's public certificate), then:

```
py -m edge_mqtt_bridge run --serial-port COM4 --mqtt-user bridge --mqtt-port 8883 --mqtt-tls-ca C:\path\to\ca.crt
py -m edge_mqtt_bridge check --mqtt-user reader --mqtt-port 8883 --mqtt-tls-ca C:\path\to\ca.crt
```

`ca.key` is the one file that must never leave a safe place: with it anyone can make a certificate the bridge will trust.

## A mistake of mine, kept here on purpose

The first version of these setup notes did not set the password file's group or mode, so following them gave "Unable to open pwfile" and a broker that would not start.
It was found when the setup was run for real on a laptop, not by the automated tests, because the tests build their own files and run the broker as the file's owner.
