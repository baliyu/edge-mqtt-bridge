"""TLS against a real Mosquitto broker, with certificates made by docs/make-certs.sh. Skipped when mosquitto or openssl is missing."""
import itertools
import os
import shutil
import socket
import subprocess
import threading
import time
from pathlib import Path

import pytest

from conftest import FakeSerial, line
from edge_mqtt_bridge.__main__ import main
from edge_mqtt_bridge.bridge import Bridge, PahoPublisher, topics
from edge_mqtt_bridge.check import run_check
from edge_mqtt_bridge.tls import make_context, plaintext_warning

pytestmark = pytest.mark.skipif(not all(shutil.which(x) for x in ("mosquitto", "mosquitto_passwd", "openssl", "bash")),
                                reason="mosquitto, mosquitto_passwd, openssl and bash are needed")
ROOT = Path(__file__).resolve().parents[1]
ACL = ROOT / "docs" / "mosquitto-acl.example"
SCRIPT = ROOT / "docs" / "make-certs.sh"
USERS = {"bridge": "bridge-pw-1", "reader": "reader-pw-2"}


def make_certs(directory, san="DNS:localhost,IP:127.0.0.1", days="30"):
    subprocess.run(["bash", str(SCRIPT), str(directory), days, san], check=True, capture_output=True)
    return Path(directory)


def start_broker(tmp_path, certs):
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        port = s.getsockname()[1]
    pw = tmp_path / "passwd"
    for i, (u, p) in enumerate(USERS.items()):
        subprocess.run(["mosquitto_passwd", "-b"] + (["-c"] if i == 0 else []) + [str(pw), u, p], check=True, capture_output=True)
    run_as = "user root\n" if os.geteuid() == 0 else ""
    conf = tmp_path / "mosquitto.conf"
    conf.write_text(f"{run_as}listener {port} 127.0.0.1\ncafile {certs / 'ca.crt'}\ncertfile {certs / 'server.crt'}\nkeyfile {certs / 'server.key'}\n"
                    f"allow_anonymous false\npassword_file {pw}\nacl_file {ACL}\npersistence false\n")
    proc = subprocess.Popen(["mosquitto", "-c", str(conf)], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    for _ in range(50):
        try:
            socket.create_connection(("127.0.0.1", port), timeout=0.2).close()
            break
        except OSError:
            time.sleep(0.1)
    return proc, port


@pytest.fixture
def tls_broker(tmp_path):
    certs = make_certs(tmp_path / "certs")
    proc, port = start_broker(tmp_path, certs)
    yield port, certs
    proc.terminate()
    proc.wait(timeout=5)


def publisher(port, ca=None, user="bridge", device="edge-1", host="127.0.0.1"):
    return PahoPublisher(host, port, f"tls-{next(_n)}", topics("edge", device)["status"], username=user, password=USERS[user], tls_ca=ca)


_n = itertools.count()


def test_a_client_that_trusts_the_authority_connects_over_tls_1_2_or_newer(tls_broker):
    port, certs = tls_broker
    p = publisher(port, str(certs / "ca.crt"))
    p.connect()
    assert p.status_accepted(timeout=5) is True
    assert p.client.socket().version() in ("TLSv1.2", "TLSv1.3")
    p.close()


def test_a_plain_client_cannot_use_the_tls_port(tls_broker):
    port, _ = tls_broker
    p = publisher(port, None)
    with pytest.raises(ConnectionError):
        p.connect(timeout=3)


def test_a_certificate_from_an_authority_the_client_does_not_trust_is_refused(tls_broker, tmp_path):
    port, _ = tls_broker
    other = make_certs(tmp_path / "other-ca")                       # a different authority: same names, different signer
    p = publisher(port, str(other / "ca.crt"))
    with pytest.raises(ConnectionError) as e:
        p.connect(timeout=3)
    assert "certificate" in str(e.value).lower()


def test_a_certificate_for_another_hostname_is_refused(tmp_path):
    certs = make_certs(tmp_path / "wrong-name", san="DNS:example.invalid")          # trusted authority, but the name does not match
    proc, port = start_broker(tmp_path, certs)
    try:
        p = publisher(port, str(certs / "ca.crt"))
        with pytest.raises(ConnectionError) as e:
            p.connect(timeout=3)
        assert "mismatch" in str(e.value).lower() or "hostname" in str(e.value).lower() or "doesn't match" in str(e.value).lower()
    finally:
        proc.terminate()
        proc.wait(timeout=5)


def test_users_and_permissions_still_apply_over_tls_and_the_stream_checks_out(tls_broker):
    port, certs = tls_broker
    ca = str(certs / "ca.crt")
    bad = publisher(port, ca, user="bridge")
    bad.client.username_pw_set("bridge", "wrong")
    with pytest.raises(ConnectionError) as e:
        bad.connect(timeout=3)
    assert "wrong" not in str(e.value)
    p = publisher(port, ca)
    p.connect()
    out = {}
    th = threading.Thread(target=lambda: out.update(r=run_check("127.0.0.1", port, "edge/+/mic", 12, 10, "reader", USERS["reader"], tls_ca=ca)))
    th.start()
    time.sleep(1.0)
    Bridge(p).run(FakeSerial([line(w) for w in range(1, 13)]))
    th.join()
    checker, error = out["r"]
    assert error is None and checker.count == 12 and checker.problems == []
    other = publisher(port, ca, device="other-device")
    other.connect()
    assert other.status_accepted(timeout=5) is False                 # the permission file still confines the bridge user
    for q in (p, other):
        q.close()


def test_the_command_line_takes_the_certificate_authority(tls_broker, monkeypatch, capsys):
    port, certs = tls_broker
    monkeypatch.setenv("EDGE_MQTT_PASSWORD", USERS["reader"])
    base = ["check", "--mqtt-host", "127.0.0.1", "--mqtt-port", str(port), "--mqtt-user", "reader", "--device", "nobody", "--count", "2", "--timeout", "2"]
    assert main(base + ["--mqtt-tls-ca", str(certs / "ca.crt")]) == 1
    assert "No messages arrived" in capsys.readouterr().err               # it connected over TLS and simply heard nothing
    assert main(base) == 1                                               # without the CA it cannot even connect
    err = capsys.readouterr().err
    assert "never got an MQTT session" in err and "--mqtt-tls-ca" in err and "No messages arrived" not in err
    assert main(base + ["--mqtt-tls-ca", str(certs / "missing.crt")]) == 2
    assert "does not exist" in capsys.readouterr().err


def test_the_context_trusts_only_the_named_authority_and_demands_a_name_and_tls_1_2(tmp_path):
    import ssl
    certs = make_certs(tmp_path / "c")
    ctx = make_context(str(certs / "ca.crt"))
    assert ctx.verify_mode == ssl.CERT_REQUIRED and ctx.check_hostname
    assert ctx.minimum_version >= ssl.TLSVersion.TLSv1_2
    assert len(ctx.get_ca_certs()) == 1                                   # only our authority, not the system's list
    assert ctx.verify_flags & ssl.VERIFY_X509_STRICT                      # strict on every Python version, as Python 3.13 does by default


def test_a_password_sent_without_tls_to_another_machine_gets_a_warning():
    assert plaintext_warning("localhost", "bridge", None) is None
    assert plaintext_warning("127.0.0.1", "bridge", None) is None
    assert plaintext_warning("broker.example", None, None) is None        # no password, nothing to leak
    assert plaintext_warning("broker.example", "bridge", "ca.crt") is None
    w = plaintext_warning("broker.example", "bridge", None)
    assert w and "without TLS" in w and "bridge" in w
