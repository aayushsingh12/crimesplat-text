"""Turn date phrases from case text into closed intervals.

Every time in the graph is an interval [start, end] of ISO datetimes plus a precision label,
because case text is rarely exact ("mid-August 2002", "1985 - 1990").
"""
from __future__ import annotations

import calendar
import re

MONTHS = {m.lower(): i for i, m in enumerate(calendar.month_name) if m}
MONTHS.update({m.lower(): i for i, m in enumerate(calendar.month_abbr) if m})
MONTHS["sept"] = 9
_MON = r"(jan(?:uary)?|feb(?:ruary)?|mar(?:ch)?|apr(?:il)?|may|jun(?:e)?|jul(?:y)?|aug(?:ust)?|sep(?:t(?:ember)?)?|oct(?:ober)?|nov(?:ember)?|dec(?:ember)?)\.?"
_TIME = re.compile(r"(\d{1,2})(?::(\d{2}))?\s*([ap])\.?\s*m\.?", re.I)


def _day(y, m, d, end=False):
    return f"{y:04d}-{m:02d}-{d:02d}T{'23:59' if end else '00:00'}"


def _month(y, m):
    return _day(y, m, 1), _day(y, m, calendar.monthrange(y, m)[1], True)


def parse(text: str):
    """Return {"start","end","precision","text"} or None if no date is found."""
    raw = text.strip()
    t = raw.lower().replace("–", "-").replace("—", "-")
    out = None

    # 1985 - 1990
    m = re.fullmatch(r"\D*(\d{4})\s*-\s*(\d{4})\D*", t)
    if m:
        out = (_day(int(m[1]), 1, 1), _day(int(m[2]), 12, 31, True), "year-range")

    # May 17 through May 20, 2010
    if not out:
        m = re.search(_MON + r"\s+(\d{1,2})\s+(?:through|to)\s+" + _MON + r"\s+(\d{1,2}),?\s+(\d{4})", t)
        if m:
            y = int(m[5])
            out = (_day(y, MONTHS[m[1][:3]], int(m[2])), _day(y, MONTHS[m[3][:3]], int(m[4]), True), "day-range")

    # spring / summer / fall / winter 2002
    if not out:
        m = re.search(r"(spring|summer|fall|autumn|winter)(?:\s+and\s+(spring|summer|fall|autumn|winter))?\s+(\d{4})", t)
        if m:
            span = {"spring": (3, 5), "summer": (6, 8), "fall": (9, 11), "autumn": (9, 11), "winter": (12, 12)}
            y, a, b = int(m[3]), span[m[1]], span[m[2] or m[1]]
            out = (_day(y, a[0], 1), _month(y, b[1])[1], "season")

    # August 15 - 17, 2002  /  August 15, 2002  /  Aug. 15 2002
    if not out:
        m = re.search(_MON + r"\s+(\d{1,2})(?:st|nd|rd|th)?(?:\s*-\s*(\d{1,2}))?,?\s+(\d{4})", t)
        if m:
            mo, y = MONTHS[m[1][:3]], int(m[4])
            d1, d2 = int(m[2]), int(m[3] or m[2])
            out = (_day(y, mo, d1), _day(y, mo, d2, True), "day" if d1 == d2 else "day-range")

    # early / mid / late August 2002, August 2002
    if not out:
        m = re.search(r"(early|mid|late)?[\s-]*" + _MON + r",?\s+(\d{4})", t)
        if m:
            mo, y = MONTHS[m[2][:3]], int(m[3])
            s, e = _month(y, mo)
            last = calendar.monthrange(y, mo)[1]
            part = {"early": (1, 10), "mid": (11, 20), "late": (21, last)}.get(m[1] or "")
            if part:
                s, e = _day(y, mo, part[0]), _day(y, mo, part[1], True)
            out = (s, e, "part-of-month" if part else "month")

    # 1990s, mid-1980s
    if not out:
        m = re.search(r"(early|mid|late)?[\s-]*(\d{3})0s", t)
        if m:
            y = int(m[2]) * 10
            lo, hi = {"early": (0, 3), "mid": (3, 7), "late": (7, 9)}.get(m[1] or "", (0, 9))
            out = (_day(y + lo, 1, 1), _day(y + hi, 12, 31, True), "decade")

    # 2002
    if not out:
        m = re.search(r"\b(19\d{2}|20\d{2})\b", t)
        if m:
            y = int(m[1])
            out = (_day(y, 1, 1), _day(y, 12, 31, True), "year")

    if not out:
        return None
    start, end, precision = out

    # a clock time narrows a single day to a minute
    tm = _TIME.search(t)
    if tm and precision == "day":
        h = int(tm[1]) % 12 + (12 if tm[3].lower() == "p" else 0)
        stamp = f"{start[:10]}T{h:02d}:{int(tm[2] or 0):02d}"
        start, end, precision = stamp, stamp, "minute"
    return {"start": start, "end": end, "precision": precision, "text": raw}
