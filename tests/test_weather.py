"""Tests for the Sencrop weather entity."""

from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock

import pytest
from homeassistant.const import STATE_UNAVAILABLE, STATE_UNKNOWN
from homeassistant.core import HomeAssistant
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import entity_registry as er
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.sencrop.api import AggregateBucket
from custom_components.sencrop.const import DOMAIN

from .conftest import setup_entry

pytestmark = pytest.mark.usefixtures("frozen_now")

WEATHER = "weather.station_sencrop"


async def test_weather_attributes(
    hass: HomeAssistant, mock_client: AsyncMock, mock_config_entry: MockConfigEntry
) -> None:
    await setup_entry(hass, mock_config_entry)

    state = hass.states.get(WEATHER)
    assert state is not None
    # First selected devices in API order: 1005 (Raincrop) then 1011 (Windcrop).
    assert state.attributes["temperature"] == 10.7
    assert state.attributes["humidity"] == 79
    assert state.attributes["dew_point"] == 7.2
    assert state.attributes["wind_speed"] == 3.0
    assert state.attributes["wind_gust_speed"] == 8.5
    assert state.attributes["wind_bearing"] == 74.0
    assert state.attributes["temperature_unit"] == "°C"
    assert state.attributes["wind_speed_unit"] == "km/h"
    assert er.async_get(hass).async_get(WEATHER).unique_id == "station_12345"


async def test_weather_condition_none(
    hass: HomeAssistant, mock_client: AsyncMock, mock_config_entry: MockConfigEntry
) -> None:
    await setup_entry(hass, mock_config_entry)

    assert hass.states.get(WEATHER).state == STATE_UNKNOWN


async def test_weather_condition_rainy(
    hass: HomeAssistant, mock_client: AsyncMock, mock_config_entry: MockConfigEntry
) -> None:
    original = mock_client.async_get_hourly.side_effect

    def hourly(device_id, measures, days, time_zone, now):
        buckets = original(device_id, measures, days, time_zone, now)
        # 0.4 mm during the previous hour (22:00-23:00 UTC).
        rain = AggregateBucket(
            datetime(2026, 10, 17, 22, tzinfo=UTC), {"RAIN_FALL": 0.4}, 4
        )
        return [b for b in buckets if b.start != rain.start] + [rain]

    mock_client.async_get_hourly.side_effect = hourly

    await setup_entry(hass, mock_config_entry)

    assert hass.states.get(WEATHER).state == "rainy"


async def test_weather_without_temperature(
    hass: HomeAssistant,
    mock_client: AsyncMock,
    mock_config_entry: MockConfigEntry,
    freezer,
) -> None:
    await setup_entry(hass, mock_config_entry)
    freezer.tick(timedelta(hours=3))

    await mock_config_entry.runtime_data.async_refresh()
    await hass.async_block_till_done()

    assert hass.states.get(WEATHER).state == STATE_UNAVAILABLE


async def test_weather_device(
    hass: HomeAssistant, mock_client: AsyncMock, mock_config_entry: MockConfigEntry
) -> None:
    await setup_entry(hass, mock_config_entry)

    registry = dr.async_get(hass)
    station = registry.async_get_device_by_identifier(
        (DOMAIN, "station_12345"), mock_config_entry.entry_id
    )
    assert station is not None
    assert station.name == "Station Sencrop"
    assert station.entry_type is dr.DeviceEntryType.SERVICE
    entry = er.async_get(hass).async_get(WEATHER)
    assert entry.device_id == station.id
