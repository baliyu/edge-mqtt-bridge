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
