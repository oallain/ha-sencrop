"""Tests for the Sencrop API response parsers."""

from datetime import UTC, datetime

import pytest

from custom_components.sencrop.api import (
    SencropResponseError,
    parse_aggregates,
    parse_devices,
    parse_latest,
    parse_me,
    parse_session_token,
    parse_whoami,
)

from .common import load_fixture, make_jwt


def test_parse_devices_from_fixture() -> None:
    devices = parse_devices(load_fixture("devices"))

    assert list(devices) == list(range(1001, 1013))
    jardin = devices[1012]
    assert jardin.name == "Raincrop jardin"
    assert jardin.named is True
    assert jardin.model == "Raincrop"
    assert jardin.battery_mv == 3552
    assert jardin.link_quality == "good"
    assert jardin.firmware == "0.2.60"
    assert jardin.serial == "SERIAL-22"
    assert "RAIN_FALL" in jardin.measures
    assert "TEMPERATURE" in jardin.measures
    assert jardin.last_status_update == datetime(2026, 10, 17, 22, 58, 11, tzinfo=UTC)
    assert devices[1001].name == "Raincrop 1001"
    assert devices[1001].named is False


def _device_payload(device: dict) -> dict:
    return {"items": [7], "devices": {"7": {"id": 7, **device}}, "models": {}}


def test_parse_devices_normalizes_legacy_measures() -> None:
    payload = _device_payload(
        {
            "contents": {"name": "Old"},
            "measures": {"list": ["RAIN_TIC", "RAIN_FALL", "TEMP_AIR_H1"]},
        }
    )

    assert parse_devices(payload)[7].measures == ("RAIN_FALL", "TEMPERATURE")


def test_parse_devices_limited_device() -> None:
    payload = _device_payload({"contents": {"name": ""}})

    device = parse_devices(payload)[7]

    assert device.battery_mv is None
    assert device.link_quality is None
    assert device.serial is None
    assert device.model is None
    assert device.measures == ()
    assert device.name == "Sencrop 7"


def test_parse_me() -> None:
    assert parse_me(load_fixture("me")) == 12345


def test_parse_session_token() -> None:
    assert parse_session_token(load_fixture("ory_login")) == "REDACTED"
    with pytest.raises(SencropResponseError):
        parse_session_token({})


def test_parse_whoami() -> None:
    token = make_jwt(1792300000)

    assert parse_whoami({"tokenized": token}) == (
        token,
        datetime.fromtimestamp(1792300000, UTC),
    )


@pytest.mark.parametrize("payload", [{}, {"tokenized": "not-a-jwt"}])
def test_parse_whoami_invalid(payload: dict) -> None:
    with pytest.raises(SencropResponseError):
        parse_whoami(payload)


def test_parse_latest_from_fixture() -> None:
    latest = parse_latest(load_fixture("raw_wind4"))

    assert {k: v.value for k, v in latest.items()} == {
        "WIND_SPEED": 3,
        "WIND_GUST": 8.5,
        "WIND_DIRECTION": 74,
    }
    assert latest["WIND_SPEED"].date == datetime(2026, 10, 17, 22, 58, 39, tzinfo=UTC)


def test_parse_latest_keeps_most_recent_per_type() -> None:
    latest = parse_latest(load_fixture("raw_rain8"))

    assert latest["RAIN_FALL"].date == datetime(2026, 10, 17, 22, 57, 53, tzinfo=UTC)
    assert latest["TEMPERATURE"].value == 11.15
    assert latest["TEMPERATURE"].date == datetime(2026, 10, 17, 22, 52, 53, tzinfo=UTC)


def test_parse_latest_skips_discarded_and_unsorted() -> None:
    payload = [
        {"type": "TEMPERATURE", "value": 12.0, "date": "2026-10-17T10:00:00.000Z"},
        {
            "type": "TEMPERATURE",
            "value": 99.0,
            "date": "2026-10-17T10:15:00.000Z",
            "discarded": True,
        },
        {"type": "TEMPERATURE", "value": 11.0, "date": "2026-10-17T09:45:00.000Z"},
    ]

    latest = parse_latest(payload)

    assert latest["TEMPERATURE"].value == 12.0
    assert latest["TEMPERATURE"].date == datetime(2026, 10, 17, 10, 0, tzinfo=UTC)


def test_parse_latest_normalizes_legacy_types() -> None:
    payload = [{"type": "RAIN_TIC", "value": 0.2, "date": "2026-10-17T10:00:00Z"}]

    assert parse_latest(payload)["RAIN_FALL"].value == 0.2


def test_parse_latest_empty() -> None:
    assert parse_latest(load_fixture("raw_wind")) == {}


def test_parse_aggregates_from_fixture() -> None:
    buckets = parse_aggregates(load_fixture("daily_rain3"))

    assert len(buckets) == 8
    assert [b.start for b in buckets] == sorted(b.start for b in buckets)
    assert buckets[0].start == datetime(2026, 10, 11, tzinfo=UTC)
    assert {"TEMPERATURE_MIN", "TEMPERATURE_MAX", "RAIN_FALL"} <= set(buckets[0].values)
    assert buckets[-1].start == datetime(2026, 10, 18, tzinfo=UTC)
    assert buckets[-1].values["TEMPERATURE_MIN"] == 10.733


def test_parse_aggregates_skips_empty_measures() -> None:
    payload = {
        "measures": {
            "interval": "1d",
            "data": [{"key": 1792281600000, "RAIN_FALL": {}, "docCount": 0}],
        }
    }

    (bucket,) = parse_aggregates(payload)

    assert bucket.values == {}
    assert bucket.count == 0


@pytest.mark.parametrize(
    ("parser", "payload"),
    [
        (parse_devices, {}),
        (parse_devices, {"items": "1", "devices": {}}),
        (parse_aggregates, {"measures": {}}),
        (parse_latest, {"not": "a list"}),
        (parse_me, {}),
    ],
)
def test_parse_invalid_payloads(parser, payload) -> None:
    with pytest.raises(SencropResponseError):
        parser(payload)


def test_parse_devices_tolerates_null_fields() -> None:
    payload = load_fixture("devices")
    payload["devices"]["1002"]["contents"] = {"name": None}
    payload["devices"]["1002"]["measures"] = {"list": None}
    payload["devices"]["1002"]["status"]["lastStatusUpdateDate"] = "not a date"

    devices = parse_devices(payload)

    assert len(devices) == 12
    assert devices[1002].name == "Raincrop 1002"
    assert devices[1002].measures == ()
    assert devices[1002].last_status_update is None


def test_parse_devices_skips_broken_entries() -> None:
    payload = load_fixture("devices")
    payload["items"].append(4242)
    payload["devices"]["1003"] = "garbage"

    devices = parse_devices(payload)

    assert 1003 not in devices
    assert 4242 not in devices
    assert devices[1012].name == "Raincrop jardin"
