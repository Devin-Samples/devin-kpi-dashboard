"""Time helpers. Consumption endpoints bucket by local midnight in the
configured timezone (default America/Los_Angeles): 08:00 UTC in winter
(PST), 07:00 UTC in summer (PDT)."""

from __future__ import annotations

from datetime import UTC, date, datetime, time, timedelta
from zoneinfo import ZoneInfo

DEFAULT_TZ = "America/Los_Angeles"


def pacific_day_start(d: date, tz: str = DEFAULT_TZ) -> int:
    """Epoch seconds of local midnight on date `d` in timezone `tz` (DST-aware)."""
    return int(datetime.combine(d, time.min, tzinfo=ZoneInfo(tz)).timestamp())


def day_windows(since: datetime, until: datetime, tz: str = DEFAULT_TZ) -> list[tuple[int, int]]:
    """Split [since, until) into per-day windows snapped to local-midnight
    boundaries in `tz`. Returns list of (start_epoch, end_epoch)."""
    zone = ZoneInfo(tz)
    start_day = since.astimezone(zone).date()
    end_day = (until - timedelta(seconds=1)).astimezone(zone).date()
    windows: list[tuple[int, int]] = []
    d = start_day
    while d <= end_day:
        s = pacific_day_start(d, tz)
        e = pacific_day_start(d + timedelta(days=1), tz)
        windows.append((max(s, int(since.timestamp())), min(e, int(until.timestamp()))))
        d += timedelta(days=1)
    return windows


def utc_now_epoch() -> int:
    return int(datetime.now(tz=UTC).timestamp())
