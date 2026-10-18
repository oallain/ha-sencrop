"""Tests for the Sencrop sensor entities."""

from dataclasses import replace
from datetime import datetime, timedelta
from unittest.mock import AsyncMock

import pytest
from freezegun.api import FrozenDateTimeFactory
from homeassistant.const import STATE_UNAVAILABLE
from homeassistant.core import HomeAssistant, State
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import entity_registry as er
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.sencrop.api import SencropConnectionError
from custom_components.sencrop.const import DOMAIN

from .conftest import setup_entry

pytestmark = pytest.mark.usefixtures("frozen_now")

RAINCROP = 1012
FERME_RAIN = 1005
WINDCROP = 1011


def entity_id(hass: HomeAssistant, device_id: int, key: str) -> str | None:
    return er.async_get(hass).async_get_entity_id(
        "sensor", DOMAIN, f"{device_id}_{key}"
    )


def state(hass: HomeAssistant, device_id: int, key: str) -> State:
    eid = entity_id(hass, device_id, key)
    assert eid is not None, f"no entity for {device_id}_{key}"
    current = hass.states.get(eid)
    assert current is not None
    return current


@pytest.fixture
async def loaded(
    hass: HomeAssistant,
    frozen_now: datetime,
    mock_client: AsyncMock,
    mock_config_entry: MockConfigEntry,
) -> MockConfigEntry:
    # Depend on frozen_now explicitly: function-level usefixtures marks run
    # before the module pytestmark, which would set up at the real time.
    await setup_entry(hass, mock_config_entry)
    return mock_config_entry


@pytest.mark.usefixtures("loaded")
async def test_entities_created_per_capabilities(hass: HomeAssistant) -> None:
    rain_keys = {
        "rain",
        "rain_today",
        "rain_24h",
        "rain_7d",
        "temperature",
        "humidity",
        "wet_temperature",
        "dew_point",
        "temperature_min_today",
        "temperature_max_today",
    }
    wind_keys = {"wind_speed", "wind_gust", "wind_direction"}
    diagnostic_keys = {"battery_voltage", "link_quality", "last_measurement"}

    for key in rain_keys | diagnostic_keys:
        assert entity_id(hass, RAINCROP, key), key
    for key in wind_keys | diagnostic_keys:
        assert entity_id(hass, WINDCROP, key), key
    for key in wind_keys:
        assert entity_id(hass, RAINCROP, key) is None
    for key in rain_keys:
        assert entity_id(hass, WINDCROP, key) is None
    assert entity_id(hass, 1004, "wind_speed") is None


@pytest.mark.usefixtures("loaded")
async def test_entity_naming(hass: HomeAssistant) -> None:
    assert entity_id(hass, RAINCROP, "temperature") == (
        "sensor.raincrop_jardin_temperature"
    )
    assert entity_id(hass, RAINCROP, "rain_7d") == (
        "sensor.raincrop_jardin_rain_last_7_days"
    )


@pytest.mark.usefixtures("loaded")
async def test_measure_states(hass: HomeAssistant) -> None:
    temperature = state(hass, RAINCROP, "temperature")
    assert temperature.state == "11.15"
    assert temperature.attributes["unit_of_measurement"] == "°C"
    assert temperature.attributes["device_class"] == "temperature"
    assert temperature.attributes["state_class"] == "measurement"
    assert state(hass, RAINCROP, "humidity").state == "72.55"
    assert state(hass, RAINCROP, "wet_temperature").state == "8.72"
    assert state(hass, RAINCROP, "rain").attributes["unit_of_measurement"] == "mm"

    speed = state(hass, WINDCROP, "wind_speed")
    assert speed.state == "3.0"
    assert speed.attributes["unit_of_measurement"] == "km/h"
    assert speed.attributes["device_class"] == "wind_speed"
    assert state(hass, WINDCROP, "wind_gust").state == "8.5"
    direction = state(hass, WINDCROP, "wind_direction")
    assert direction.state == "74.0"
    assert direction.attributes["device_class"] == "wind_direction"
    assert direction.attributes["state_class"] == "measurement_angle"
    assert direction.attributes["unit_of_measurement"] == "°"


@pytest.mark.usefixtures("loaded")
async def test_rain_aggregates(hass: HomeAssistant) -> None:
    # Pluviometre verger: 0.762 mm on the 14th, 2.794 mm on the 17th (07-10 UTC).
    today = state(hass, FERME_RAIN, "rain_today")
    assert today.state == "0.0"
    assert today.attributes["state_class"] == "total"
    assert today.attributes["device_class"] == "precipitation"
    assert today.attributes["last_reset"] == "2026-10-18T00:00:00+02:00"
    assert state(hass, FERME_RAIN, "rain_24h").state == "2.8"
    assert state(hass, FERME_RAIN, "rain_7d").state == "3.6"
    assert state(hass, RAINCROP, "rain_24h").state == "0.0"


@pytest.mark.usefixtures("loaded")
async def test_temperature_extremes_today(hass: HomeAssistant) -> None:
    assert state(hass, RAINCROP, "temperature_min_today").state == "11.15"
    assert state(hass, RAINCROP, "temperature_max_today").state == "11.676"


@pytest.mark.usefixtures("loaded")
async def test_dew_point_state(hass: HomeAssistant) -> None:
    dew = state(hass, RAINCROP, "dew_point")

    assert dew.state == "6.4"
    assert dew.attributes["device_class"] == "temperature"


@pytest.mark.usefixtures("loaded")
async def test_diagnostics_entities(hass: HomeAssistant) -> None:
    battery = state(hass, RAINCROP, "battery_voltage")
    assert battery.state == "3552"
    assert battery.attributes["unit_of_measurement"] == "mV"
    assert battery.attributes["device_class"] == "voltage"
    link = state(hass, RAINCROP, "link_quality")
    assert link.state == "good"
    assert link.attributes["options"] == [
        "excellent",
        "good",
        "average",
        "limit",
        "unknown",
    ]
    assert state(hass, RAINCROP, "last_measurement").state == (
        "2026-10-17T22:57:53+00:00"
    )
    entry = er.async_get(hass).async_get(entity_id(hass, RAINCROP, "battery_voltage"))
    assert entry.entity_category is er.EntityCategory.DIAGNOSTIC


async def test_unknown_link_quality(
    hass: HomeAssistant, mock_client: AsyncMock, mock_config_entry: MockConfigEntry
) -> None:
    devices = mock_client.async_get_devices.return_value
    devices[RAINCROP] = replace(devices[RAINCROP], link_quality="weird")

    await setup_entry(hass, mock_config_entry)

    assert state(hass, RAINCROP, "link_quality").state == "unknown"


async def test_stale_device_unavailable(
    hass: HomeAssistant, loaded: MockConfigEntry, freezer: FrozenDateTimeFactory
) -> None:
    freezer.tick(timedelta(hours=3))
    await loaded.runtime_data.async_refresh()
    await hass.async_block_till_done()

    assert state(hass, RAINCROP, "temperature").state == STATE_UNAVAILABLE
    assert state(hass, RAINCROP, "rain_7d").state == STATE_UNAVAILABLE
    assert state(hass, RAINCROP, "battery_voltage").state == "3552"


async def test_coordinator_failure_unavailable(
    hass: HomeAssistant, loaded: MockConfigEntry, mock_client: AsyncMock
) -> None:
    mock_client.async_get_devices.side_effect = SencropConnectionError("down")

    await loaded.runtime_data.async_refresh()
    await hass.async_block_till_done()

    assert state(hass, RAINCROP, "temperature").state == STATE_UNAVAILABLE
    assert state(hass, RAINCROP, "battery_voltage").state == STATE_UNAVAILABLE


async def test_device_removed_from_account(
    hass: HomeAssistant, loaded: MockConfigEntry, mock_client: AsyncMock
) -> None:
    devices = dict(mock_client.async_get_devices.return_value)
    del devices[RAINCROP]
    mock_client.async_get_devices.return_value = devices

    await loaded.runtime_data.async_refresh()
    await hass.async_block_till_done()

    assert state(hass, RAINCROP, "temperature").state == STATE_UNAVAILABLE
    assert state(hass, WINDCROP, "wind_speed").state == "3.0"


async def test_device_info(hass: HomeAssistant, loaded: MockConfigEntry) -> None:
    device = dr.async_get(hass).async_get_device_by_identifier(
        (DOMAIN, "1012"), loaded.entry_id
    )

    assert device is not None
    assert device.name == "Raincrop jardin"
    assert device.manufacturer == "Sencrop"
    assert device.model == "Raincrop"
    assert device.serial_number == "SERIAL-22"
    assert device.sw_version == "0.2.60"


@pytest.mark.usefixtures("loaded")
async def test_firmware_disabled_by_default(hass: HomeAssistant) -> None:
    entry = er.async_get(hass).async_get(entity_id(hass, RAINCROP, "firmware"))

    assert entry is not None
    assert entry.disabled_by is er.RegistryEntryDisabler.INTEGRATION


@pytest.mark.parametrize(
    ("current", "expected_min", "expected_max"),
    [(12.5, "11.15", "12.5"), (10.0, "10.0", "11.676")],
)
async def test_temperature_extremes_include_current_measure(
    hass: HomeAssistant,
    mock_client: AsyncMock,
    mock_config_entry: MockConfigEntry,
    current: float,
    expected_min: str,
    expected_max: str,
) -> None:
    # The daily aggregate (min 11.15, max 11.676) lags behind raw measures.
    original = mock_client.async_get_latest.side_effect

    def latest(device_id, measures, now):
        values = original(device_id, measures, now)
        if device_id == RAINCROP:
            values["TEMPERATURE"] = replace(values["TEMPERATURE"], value=current)
        return values

    mock_client.async_get_latest.side_effect = latest

    await setup_entry(hass, mock_config_entry)

    assert state(hass, RAINCROP, "temperature_min_today").state == expected_min
    assert state(hass, RAINCROP, "temperature_max_today").state == expected_max
