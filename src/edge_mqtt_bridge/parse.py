"""Reading the Edge's serial lines: which lines are real windows, and which are stale or repeated.

The firmware (mic_logger, in the tinyml-edge-lab repository) prints one line every 0.25 s:  w,mean,rms,peak,zcr,hf,clip,rate_hz
plus '#' comment lines. Windows can hand over old bytes when a serial port is opened, so a reader must expect cut-off lines
at the start, repeated lines, and a window number that starts again after a board reset.
"""
from __future__ import annotations

import re
from dataclasses import dataclass

FIELDS = ("w", "mean", "rms", "peak", "zcr", "hf", "clip", "rate_hz")
LINE_RE = re.compile(r"^(\d{1,9}),(\d{1,5}),(\d{1,5}),(\d{1,5}),(\d{1,5}),(\d{1,5}),(\d{1,5}),(\d{1,6})$")
KV_RE = re.compile(r"(\w+)=(\S+)")
MAX_COUNT = 16383    # a 14-bit ADC count cannot be larger; a bigger mean, peak or rms is a corrupted line
WINDOW_N = 2000      # samples per window; no window can have more clipped samples than this


def parse_line(text: str):
    """('row', dict), ('meta', dict), ('comment', text) or None for a blank or unreadable line."""
    text = text.strip()
    if not text:
        return None
    if text.startswith("#"):
        kv = dict(KV_RE.findall(text))
        if text.startswith("# mic_logger") and "window" in kv:
            try:
                banner = " ".join(text[1:].split()[:2])            # e.g. "mic_logger v1"
                return ("meta", {"banner": banner, "window": int(kv["window"]), "fs_target": int(kv.get("fs_target", 0))})
            except ValueError:
                return None
        return ("comment", text)
    m = LINE_RE.match(text)
    if not m:
        return None
    row = dict(zip(FIELDS, (int(g) for g in m.groups())))
    if max(row["mean"], row["peak"], row["rms"]) > MAX_COUNT or row["clip"] > WINDOW_N:
        return None
    return ("row", row)


@dataclass
class Counters:
    received: int = 0       # readable window lines seen (including repeats)
    accepted: int = 0       # windows passed on
    duplicates: int = 0     # a window number seen twice in a row
    restarts: int = 0       # the window number went backwards: the board restarted
    stale: int = 0          # unreadable lines before the first good window
    bad: int = 0            # unreadable lines after it


class LineFilter:
    """Turns raw lines into accepted windows. feed() returns ('row', dict) for a new window, ('meta', dict) for the
    firmware's header line, or None for everything else; the counts say what was dropped and why."""

    def __init__(self):
        self.counters = Counters()
        self._last_w = None

    def feed(self, text: str):
        item = parse_line(text)
        c = self.counters
        if item is None:
            if text.strip():
                if self._last_w is None:
                    c.stale += 1
                else:
                    c.bad += 1
            return None
        kind, value = item
        if kind == "meta":
            return item
        if kind == "comment":
            return None
        c.received += 1
        w = value["w"]
        if self._last_w is not None and w == self._last_w:
            c.duplicates += 1
            return None
        if self._last_w is not None and w < self._last_w:
            c.restarts += 1
        self._last_w = w
        c.accepted += 1
        return item
