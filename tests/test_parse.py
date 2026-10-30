from conftest import HEADER, line
from edge_mqtt_bridge.parse import LineFilter, parse_line


def test_a_good_line_is_a_row():
    kind, row = parse_line(line(7, rms=150))
    assert kind == "row" and row["w"] == 7 and row["rms"] == 150 and row["rate_hz"] == 7887


def test_the_header_is_meta_and_other_comments_are_comments():
    assert parse_line(HEADER) == ("meta", {"banner": "mic_logger v1", "window": 2000, "fs_target": 8000})
    assert parse_line("# w,mean,rms,peak,zcr,hf,clip,rate_hz")[0] == "comment"


def test_garbage_and_impossible_values_are_rejected():
    assert parse_line("") is None and parse_line("hello") is None
    assert parse_line("748,108,0,7888") is None                       # the tail of a line
    assert parse_line(line(3, rms=99999)) is None                     # more than a 14-bit count
    assert parse_line(line(3, clip=5000)) is None                     # more clipped samples than a window holds


def test_repeated_windows_are_dropped_once():
    f = LineFilter()
    out = [f.feed(x) for x in [line(1), line(2), line(2), line(2), line(3)]]
    assert [o[1]["w"] for o in out if o] == [1, 2, 3]
    assert f.counters.duplicates == 2 and f.counters.accepted == 3 and f.counters.received == 5


def test_a_window_number_going_backwards_is_a_restart():
    f = LineFilter()
    for x in [line(1), line(2), line(3), line(1), line(2)]:
        f.feed(x)
    assert f.counters.restarts == 1 and f.counters.accepted == 5


def test_unreadable_lines_are_stale_before_the_first_window_and_bad_after():
    f = LineFilter()
    for x in ["748,108,0,7888"] * 5 + [line(1), "garbage", line(2)]:
        f.feed(x)
    c = f.counters
    assert c.stale == 5 and c.bad == 1 and c.accepted == 2
