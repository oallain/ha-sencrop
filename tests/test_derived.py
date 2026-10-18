"""Tests for the derived weather computations."""

from datetime import UTC, date, datetime, timedelta
from zoneinfo import ZoneInfo

from custom_components.sencrop.api import AggregateBucket, Measurement, parse_aggregates
from custom_components.sencrop.derived import (
    daily_bucket,
    dew_point,
    is_stale,
    last_measurement_date,
    sum_days,
    sum_since,
    today_extreme,
)

from .common import load_fixture

NOW = datetime(2026, 10, 17, 23, 0, tzinfo=UTC)


def test_dew_point() -> None:
    assert dew_point(20.0, 50.0) == 9.3
    assert dew_point(0.0, 100.0) == 0.0
    assert dew_point(10.0, 0.0) is None


def test_daily_bucket_after_local_midnight() -> None:
    buckets = parse_aggregates(load_fixture("daily_rain3"))
    # 00:30 in Paris on the 18th is still the 17th in UTC.
    local_now = datetime(2026, 10, 17, 22, 30, tzinfo=UTC).astimezone(
        ZoneInfo("Europe/Paris")
    )

    bucket = daily_bucket(buckets, local_now.date())

    assert bucket is not None
    assert bucket.start == datetime(2026, 10, 18, tzinfo=UTC)


def test_daily_bucket_missing() -> None:
    buckets = parse_aggregates(load_fixture("daily_rain3"))

    assert daily_bucket(buckets, date(2026, 9, 1)) is None


def test_sum_days_from_fixture() -> None:
    buckets = parse_aggregates(load_fixture("daily_rain3"))

    # 0.762 mm on the 14th + 2.794 mm on the 17th.
    assert sum_days(buckets, "RAIN_FALL", date(2026, 10, 12)) == 3.6
    assert sum_days(buckets, "RAIN_FALL", date(2026, 10, 15)) == 2.8
    assert sum_days(buckets, "RAIN_FALL", date(2026, 11, 1)) is None


def _hourly(count: int, value: float) -> list[AggregateBucket]:
    return [
        AggregateBucket(
            start=NOW - timedelta(hours=count - 1 - i),
            values={"RAIN_FALL": value},
            count=4,
        )
        for i in range(count)
    ]


def test_sum_since() -> None:
    buckets = _hourly(30, 0.2)

    # Inclusive bound: 24 hourly buckets start at or after NOW - 23h.
    assert sum_since(buckets, "RAIN_FALL", NOW - timedelta(hours=23)) == 4.8
    assert sum_since(buckets, "RAIN_FALL", NOW) == 0.2
    assert sum_since(buckets, "RAIN_FALL", NOW + timedelta(hours=1)) is None


def test_sum_since_ignores_buckets_without_measure() -> None:
    buckets = [AggregateBucket(start=NOW, values={}, count=0)]

    assert sum_since(buckets, "RAIN_FALL", NOW - timedelta(hours=1)) is None


def _measure(age: timedelta) -> dict[str, Measurement]:
    return {"TEMPERATURE": Measurement("TEMPERATURE", 10.0, NOW - age)}


def test_last_measurement_date() -> None:
    latest = {
        **_measure(timedelta(minutes=30)),
        "RAIN_FALL": Measurement("RAIN_FALL", 0.0, NOW - timedelta(minutes=5)),
    }

    assert last_measurement_date(latest) == NOW - timedelta(minutes=5)
    assert last_measurement_date({}) is None


def test_is_stale() -> None:
    max_age = timedelta(hours=2)

    assert is_stale(_measure(timedelta(hours=1, minutes=59)), NOW, max_age) is False
    assert is_stale(_measure(timedelta(hours=2, minutes=1)), NOW, max_age) is True
    assert is_stale({}, NOW, max_age) is True


PARIS = ZoneInfo("Europe/Paris")
# 14:00 in Paris on the 18th; daily keys are local dates at 00:00 UTC.
LOCAL_NOW = datetime(2026, 10, 18, 14, 0, tzinfo=PARIS)
TODAY_BUCKET = AggregateBucket(
    start=datetime(2026, 10, 18, tzinfo=UTC),
    values={"TEMPERATURE_MIN": 6.1, "TEMPERATURE_MAX": 13.9},
    count=40,
)


def _temperature(value: float, when: datetime) -> Measurement:
    return Measurement("TEMPERATURE", value, when.astimezone(UTC))


def test_today_extreme_includes_current_measure() -> None:
    current = _temperature(14.75, LOCAL_NOW - timedelta(minutes=5))

    assert (
        today_extreme([TODAY_BUCKET], "TEMPERATURE_MAX", current, LOCAL_NOW, max)
        == 14.75
    )
    assert (
        today_extreme([TODAY_BUCKET], "TEMPERATURE_MIN", current, LOCAL_NOW, min) == 6.1
    )


def test_today_extreme_keeps_aggregate_when_current_is_within() -> None:
    current = _temperature(10.0, LOCAL_NOW - timedelta(minutes=5))

    assert (
        today_extreme([TODAY_BUCKET], "TEMPERATURE_MAX", current, LOCAL_NOW, max)
        == 13.9
    )
    assert (
        today_extreme([TODAY_BUCKET], "TEMPERATURE_MIN", current, LOCAL_NOW, min) == 6.1
    )


def test_today_extreme_ignores_yesterdays_measure() -> None:
    # 23:50 local on the 17th, while it is 00:10 on the 18th.
    now = datetime(2026, 10, 18, 0, 10, tzinfo=PARIS)
    yesterday = _temperature(25.0, datetime(2026, 10, 17, 23, 50, tzinfo=PARIS))

    assert today_extreme([TODAY_BUCKET], "TEMPERATURE_MAX", yesterday, now, max) == 13.9


def test_today_extreme_without_todays_bucket() -> None:
    current = _temperature(9.2, LOCAL_NOW - timedelta(minutes=5))

    assert today_extreme([], "TEMPERATURE_MAX", current, LOCAL_NOW, max) == 9.2
    assert today_extreme([], "TEMPERATURE_MAX", None, LOCAL_NOW, max) is None
