"""GTFS service days.

A GTFS time such as 25:10:00 counts from "noon minus 12 hours" on the service
date, which equals local midnight except on daylight-saving changeover days.
"""

from __future__ import annotations

import datetime as dt
from zoneinfo import ZoneInfo

from transitlive.domain.model import Timetable


def parse_date(key: str) -> dt.date:
    return dt.date(int(key[:4]), int(key[4:6]), int(key[6:8]))


def date_key(day: dt.date) -> str:
    return day.strftime("%Y%m%d")


def service_day_start(key: str, timezone: str) -> int:
    """Epoch seconds that the service date's stop times count from."""
    d = parse_date(key)
    noon = dt.datetime(d.year, d.month, d.day, 12, tzinfo=ZoneInfo(timezone))
    return int(noon.timestamp()) - 12 * 3600


def local_date(now: float, timezone: str, offset_days: int = 0) -> str:
    day = dt.datetime.fromtimestamp(now, ZoneInfo(timezone)).date() + dt.timedelta(days=offset_days)
    return date_key(day)


def hms_to_secs(t: str) -> int:
    h, m, s = (int(x) for x in t.split(":"))
    return h * 3600 + m * 60 + s


def gtfs_time(key: str, hms: str, timezone: str) -> int:
    """Epoch seconds of an HH:MM:SS time on a service date."""
    return service_day_start(key, timezone) + hms_to_secs(hms)


def recent_service_days(tt: Timetable, now: float) -> list[tuple[str, int, frozenset[str]]]:
    """Yesterday and today as (date key, day start, active service ids).

    Yesterday is included because its trips can run past midnight.
    """
    days = []
    for offset in (-1, 0):
        key = local_date(now, tt.timezone, offset)
        days.append((key, service_day_start(key, tt.timezone), tt.services.get(key, frozenset())))
    return days
