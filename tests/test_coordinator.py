"""Tests for the Sencrop data coordinator."""

from datetime import timedelta
from unittest.mock import AsyncMock

import pytest
from freezegun.api import FrozenDateTimeFactory
from homeassistant.config_entries import ConfigEntryState
from homeassistant.core import HomeAssistant
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.sencrop.api import (
    Measurement,
    SencropAuthError,
    SencropConnectionError,
    SencropResponseError,
)
from custom_components.sencrop.const import CONF_DEVICES

from .conftest import setup_entry

pytestmark = pytest.mark.usefixtures("frozen_now")


def _device_calls(mock: AsyncMock, device_id: int) -> int:
    return sum(1 for call in mock.call_args_list if call.args[0] == device_id)


async def _refresh(hass: HomeAssistant, entry: MockConfigEntry) -> None:
    await entry.runtime_data.async_refresh()
    await hass.async_block_till_done()


async def test_first_refresh_only_selected_devices(
    hass: HomeAssistant, mock_client: AsyncMock, mock_config_entry: MockConfigEntry
) -> None:
    await setup_entry(hass, mock_config_entry)

    data = mock_config_entry.runtime_data.data
    assert set(data) == {1005, 1011, 1012}
    assert data[1012].hourly
    assert data[1012].daily
    assert data[1012].latest["TEMPERATURE"].value == 11.15
    assert data[1011].hourly == []
    assert data[1011].daily == []
    assert _device_calls(mock_client.async_get_hourly, 1011) == 0
    assert _device_calls(mock_client.async_get_daily, 1011) == 0
    assert _device_calls(mock_client.async_get_latest, 1004) == 0


async def test_daily_requests_rain_and_temperature_extremes(
    hass: HomeAssistant, mock_client: AsyncMock, mock_config_entry: MockConfigEntry
) -> None:
    await setup_entry(hass, mock_config_entry)

    call = next(
        c for c in mock_client.async_get_daily.call_args_list if c.args[0] == 1012
    )
    assert call.args[1:4] == (
        ["RAIN_FALL", "TEMPERATURE_MIN", "TEMPERATURE_MAX"],
        7,
        "Europe/Paris",
    )
    hourly = next(
        c for c in mock_client.async_get_hourly.call_args_list if c.args[0] == 1012
    )
    assert hourly.args[1:4] == (["RAIN_FALL"], 2, "Europe/Paris")


async def test_selected_device_missing_from_account(
    hass: HomeAssistant, mock_client: AsyncMock
) -> None:
    entry = MockConfigEntry(
        domain="sencrop",
        unique_id="12345",
        data={"email": "user@example.com", "password": "secret"},
        options={CONF_DEVICES: ["1012", "9999"]},
    )

    await setup_entry(hass, entry)

    assert entry.state is ConfigEntryState.LOADED
    assert set(entry.runtime_data.data) == {1012}


async def test_aggregates_cached_when_no_new_measure(
    hass: HomeAssistant,
    mock_client: AsyncMock,
    mock_config_entry: MockConfigEntry,
    freezer: FrozenDateTimeFactory,
) -> None:
    await setup_entry(hass, mock_config_entry)
    freezer.tick(timedelta(minutes=5))

    await _refresh(hass, mock_config_entry)

    assert _device_calls(mock_client.async_get_daily, 1012) == 1
    assert _device_calls(mock_client.async_get_latest, 1012) == 2


async def test_aggregates_refreshed_on_new_measure(
    hass: HomeAssistant,
    mock_client: AsyncMock,
    mock_config_entry: MockConfigEntry,
    freezer: FrozenDateTimeFactory,
) -> None:
    await setup_entry(hass, mock_config_entry)
    previous = mock_config_entry.runtime_data.data[1012].latest
    newer = Measurement(
        "RAIN_FALL", 0.2, previous["RAIN_FALL"].date + timedelta(minutes=15)
    )
    mock_client.async_get_latest.side_effect = None
    mock_client.async_get_latest.return_value = {**previous, "RAIN_FALL": newer}
    freezer.tick(timedelta(minutes=5))

    await _refresh(hass, mock_config_entry)

    assert _device_calls(mock_client.async_get_daily, 1012) == 2


async def test_aggregates_refreshed_after_max_age(
    hass: HomeAssistant,
    mock_client: AsyncMock,
    mock_config_entry: MockConfigEntry,
    freezer: FrozenDateTimeFactory,
) -> None:
    await setup_entry(hass, mock_config_entry)
    freezer.tick(timedelta(minutes=31))

    await _refresh(hass, mock_config_entry)

    assert _device_calls(mock_client.async_get_daily, 1012) == 2


async def test_device_parse_error_keeps_previous_data(
    hass: HomeAssistant, mock_client: AsyncMock, mock_config_entry: MockConfigEntry
) -> None:
    await setup_entry(hass, mock_config_entry)
    before = mock_config_entry.runtime_data.data[1012]
    original = mock_client.async_get_latest.side_effect

    def failing(device_id, measures, now):
        if device_id == 1012:
            raise SencropResponseError("bad payload")
        return original(device_id, measures, now)

    mock_client.async_get_latest.side_effect = failing

    await _refresh(hass, mock_config_entry)

    coordinator = mock_config_entry.runtime_data
    assert coordinator.last_update_success
    assert coordinator.data[1012] is before
    assert _device_calls(mock_client.async_get_latest, 1011) == 2


async def test_device_parse_error_without_previous_data(
    hass: HomeAssistant, mock_client: AsyncMock, mock_config_entry: MockConfigEntry
) -> None:
    original = mock_client.async_get_latest.side_effect

    def failing(device_id, measures, now):
        if device_id == 1012:
            raise SencropResponseError("bad payload")
        return original(device_id, measures, now)

    mock_client.async_get_latest.side_effect = failing

    await setup_entry(hass, mock_config_entry)

    assert set(mock_config_entry.runtime_data.data) == {1005, 1011}


async def test_offline_device_empty_raw(
    hass: HomeAssistant, mock_client: AsyncMock, mock_config_entry: MockConfigEntry
) -> None:
    mock_client.async_get_latest.side_effect = None
    mock_client.async_get_latest.return_value = {}

    await setup_entry(hass, mock_config_entry)

    assert mock_config_entry.runtime_data.data[1012].latest == {}


async def test_auth_error_fails_update(
    hass: HomeAssistant, mock_client: AsyncMock, mock_config_entry: MockConfigEntry
) -> None:
    await setup_entry(hass, mock_config_entry)
    mock_client.async_get_devices.side_effect = SencropAuthError

    await _refresh(hass, mock_config_entry)

    assert mock_config_entry.runtime_data.last_update_success is False


@pytest.mark.parametrize(
    "error", [SencropConnectionError("down"), SencropResponseError("bad")]
)
async def test_devices_error_update_failed(
    hass: HomeAssistant,
    mock_client: AsyncMock,
    mock_config_entry: MockConfigEntry,
    error: Exception,
) -> None:
    await setup_entry(hass, mock_config_entry)
    mock_client.async_get_devices.side_effect = error

    await _refresh(hass, mock_config_entry)

    assert mock_config_entry.runtime_data.last_update_success is False


async def test_connection_error_on_device_update_failed(
    hass: HomeAssistant, mock_client: AsyncMock, mock_config_entry: MockConfigEntry
) -> None:
    await setup_entry(hass, mock_config_entry)
    mock_client.async_get_latest.side_effect = SencropConnectionError("down")

    await _refresh(hass, mock_config_entry)

    assert mock_config_entry.runtime_data.last_update_success is False
