import pytest

from edge_mqtt_bridge.__main__ import build_parser


def test_run_needs_a_serial_port():
    with pytest.raises(SystemExit):
        build_parser().parse_args(["run"])


def test_defaults():
    a = build_parser().parse_args(["run", "--serial-port", "COM4"])
    assert (a.baud, a.device, a.prefix, a.mqtt_host, a.mqtt_port) == (115200, "edge-1", "edge", "localhost", 1883)
    c = build_parser().parse_args(["check"])
    assert (c.device, c.count, c.timeout) == ("+", 40, 30.0)


def test_credentials_come_from_the_environment_and_a_missing_one_is_an_error():
    from edge_mqtt_bridge.__main__ import resolve_credentials
    assert resolve_credentials(None, "EDGE_MQTT_PASSWORD", {}) == (None, None)
    assert resolve_credentials("bridge", "EDGE_MQTT_PASSWORD", {"EDGE_MQTT_PASSWORD": "pw"}) == ("bridge", "pw")
    with pytest.raises(SystemExit) as e:
        resolve_credentials("bridge", "EDGE_MQTT_PASSWORD", {})
    assert "EDGE_MQTT_PASSWORD" in str(e.value) and "pw" not in str(e.value)


def test_there_is_no_password_argument_on_the_command_line():
    help_text = build_parser().parse_args(["run", "--serial-port", "COM4"])
    assert not hasattr(help_text, "mqtt_password")
    with pytest.raises(SystemExit):
        build_parser().parse_args(["run", "--serial-port", "COM4", "--mqtt-password", "secret"])


def test_the_final_summary_names_what_the_broker_refused():
    from edge_mqtt_bridge.__main__ import final_summary
    from edge_mqtt_bridge.bridge import Bridge

    class Pub:
        rejected = 4
        def publish(self, topic, payload, qos=0, retain=False):
            return True
    text = final_summary(Bridge(Pub()))
    assert text.startswith("Stopped.") and "refused by the broker 4" in text
    class Plain:
        def publish(self, topic, payload, qos=0, retain=False):
            return True
    assert "refused by the broker 0" in final_summary(Bridge(Plain()))
