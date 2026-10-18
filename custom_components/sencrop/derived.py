"""Values derived from Sencrop measures (no Home Assistant imports)."""

import math
from collections.abc import Callable, Iterable, Mapping, Sequence
from datetime import UTC, date, datetime, timedelta

from .api import AggregateBucket, Measurement

MAGNUS_A = 17.62
MAGNUS_B = 243.12


def dew_point(temperature: float, humidity: float) -> float | None:
    """Return the dew point in °C (Magnus formula)."""
    if humidity <= 0:
        return None
    gamma = math.log(humidity / 100) + MAGNUS_A * temperature / (MAGNUS_B + temperature)
    return round(MAGNUS_B * gamma / (MAGNUS_A - gamma), 1)


def _bucket_day(bucket: AggregateBucket) -> date:
    # Daily keys encode the local date at 00:00 UTC.
    return bucket.start.astimezone(UTC).date()


def daily_bucket(
    buckets: Sequence[AggregateBucket], day: date
) -> AggregateBucket | None:
    """Return the daily bucket of a local date."""
    return next((b for b in buckets if _bucket_day(b) == day), None)


def today_extreme(
    buckets: Sequence[AggregateBucket],
    measure: str,
    current: Measurement | None,
    now: datetime,
    pick: Callable[[Iterable[float]], float],
) -> float | None:
    """Today's min or max from the daily aggregate and the current measure.

    Sencrop refreshes the daily aggregate less often than raw measures, so
    the latest reading can already be beyond it. `now` is local time.
    """
    values = []
    bucket = daily_bucket(buckets, now.date())
    if bucket is not None and measure in bucket.values:
        values.append(bucket.values[measure])
    if current is not None and current.date.astimezone(now.tzinfo).date() == now.date():
        values.append(current.value)
    return pick(values) if values else None


def _sum(values: list[float]) -> float | None:
    return round(sum(values), 1) if values else None


def sum_since(
    buckets: Sequence[AggregateBucket], measure: str, since: datetime
) -> float | None:
    """Sum a measure over the buckets starting at or after `since`."""
    return _sum(
        [b.values[measure] for b in buckets if b.start >= since and measure in b.values]
    )


def sum_days(
    buckets: Sequence[AggregateBucket], measure: str, first_day: date
) -> float | None:
    """Sum a measure over the daily buckets from `first_day` on."""
    return _sum(
        [
            b.values[measure]
            for b in buckets
            if _bucket_day(b) >= first_day and measure in b.values
        ]
    )


def last_measurement_date(latest: Mapping[str, Measurement]) -> datetime | None:
    """Return the date of the most recent measure."""
    return max((m.date for m in latest.values()), default=None)


def is_stale(
    latest: Mapping[str, Measurement], now: datetime, max_age: timedelta
) -> bool:
    """Tell whether a device stopped reporting."""
    last = last_measurement_date(latest)
    return last is None or now - last > max_age
