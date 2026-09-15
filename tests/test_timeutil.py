from datetime import UTC, date, datetime

from devin_kpi.timeutil import day_windows, pacific_day_start


def test_pacific_day_start_pst():
    # Jan 15 2024 -> midnight PST == 08:00 UTC
    assert pacific_day_start(date(2024, 1, 15)) == int(
        datetime(2024, 1, 15, 8, 0, tzinfo=UTC).timestamp()
    )


def test_pacific_day_start_pdt():
    # Jul 15 2024 -> midnight PDT == 07:00 UTC
    assert pacific_day_start(date(2024, 7, 15)) == int(
        datetime(2024, 7, 15, 7, 0, tzinfo=UTC).timestamp()
    )


def test_dst_transition_day():
    # Spring forward 2024-03-10: the day still starts at local midnight,
    # and the next day starts 23 hours later.
    start = pacific_day_start(date(2024, 3, 10))
    nxt = pacific_day_start(date(2024, 3, 11))
    assert nxt - start == 23 * 3600
    # Fall back 2024-11-03: 25-hour day.
    start = pacific_day_start(date(2024, 11, 3))
    nxt = pacific_day_start(date(2024, 11, 4))
    assert nxt - start == 25 * 3600


def test_day_windows_snap_to_boundary():
    since = datetime(2024, 7, 14, 12, 0, tzinfo=UTC)
    until = datetime(2024, 7, 16, 12, 0, tzinfo=UTC)
    windows = day_windows(since, until)
    # Jul 14 (partial), Jul 15 (full), Jul 16 (partial) in Pacific time
    assert len(windows) == 3
    assert windows[0][0] == int(since.timestamp())
    assert windows[1][0] == pacific_day_start(date(2024, 7, 15))
    assert windows[1][1] == pacific_day_start(date(2024, 7, 16))
    assert windows[-1][1] == int(until.timestamp())


def test_day_windows_single_day():
    since = datetime(2024, 1, 15, 16, 0, tzinfo=UTC)
    until = datetime(2024, 1, 15, 17, 0, tzinfo=UTC)
    assert len(day_windows(since, until)) == 1
