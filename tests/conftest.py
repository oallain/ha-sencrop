"""Shared fixtures for the Sencrop tests."""

from collections.abc import Generator
from datetime import datetime
from unittest.mock import AsyncMock, patch

import pytest
from freezegun.api import FrozenDateTimeFactory
from homeassistant.const import CONF_EMAIL, CONF_PASSWORD
from homeassistant.core import HomeAssistant
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.sencrop.api import (
    parse_aggregates,
    parse_devices,
    parse_latest,
)
from custom_components.sencrop.const import CONF_DEVICES, CONF_SCAN_INTERVAL, DOMAIN

from .common import load_fixture

# Fixtures were captured right after 2026-10-17T23:00Z (01:00 in Paris).
FIXTURES_NOW = "2026-10-17T23:00:00+00:00"

LATEST_FIXTURES = {
    1004: "raw_wind2",
    1005: "raw_rain3",
    1011: "raw_wind4",
    1012: "raw_rain8",
}
HOURLY_FIXTURES = {1005: "hourly_rain3", 1012: "hourly_rain8"}
DAILY_FIXTURES = {1005: "daily_rain3", 1012: "daily_rain8"}
SELECTED_DEVICES = ["1005", "1011", "1012"]


@pytest.fixture(autouse=True)
def auto_enable_custom_integrations(enable_custom_integrations):
    """Enable loading custom integrations in every test."""
    return


@pytest.fixture(autouse=True)
async def paris_time_zone(hass: HomeAssistant) -> None:
    """Run every test in the Sencrop users' time zone."""
    await hass.config.async_set_time_zone("Europe/Paris")


@pytest.fixture
def frozen_now(freezer: FrozenDateTimeFactory) -> datetime:
    """Freeze time at the fixtures capture time."""
    freezer.move_to(FIXTURES_NOW)
    return datetime.fromisoformat(FIXTURES_NOW)


def _latest(device_id: int, measures, now) -> dict:
    name = LATEST_FIXTURES.get(device_id)
    return parse_latest(load_fixture(name)) if name else {}


def _hourly(device_id: int, measures, days, time_zone, now) -> list:
    name = HOURLY_FIXTURES.get(device_id)
    return parse_aggregates(load_fixture(name)) if name else []


def _daily(device_id: int, measures, days, time_zone, now) -> list:
    name = DAILY_FIXTURES.get(device_id)
    return parse_aggregates(load_fixture(name)) if name else []


@pytest.fixture
def mock_client() -> Generator[AsyncMock]:
    """Patch the Sencrop client with one answering from the fixtures."""
    client = AsyncMock()
    client.user_id = 12345
    client.async_login.return_value = 12345
    client.async_get_devices.return_value = parse_devices(load_fixture("devices"))
    client.async_get_latest.side_effect = _latest
    client.async_get_hourly.side_effect = _hourly
    client.async_get_daily.side_effect = _daily
    with patch("custom_components.sencrop.SencropClient", return_value=client):
        yield client


@pytest.fixture
def mock_config_entry() -> MockConfigEntry:
    """Return a Sencrop config entry with three selected devices."""
    return MockConfigEntry(
        domain=DOMAIN,
        unique_id="12345",
        title="user@example.com",
        data={CONF_EMAIL: "user@example.com", CONF_PASSWORD: "secret"},
        options={CONF_SCAN_INTERVAL: 5, CONF_DEVICES: SELECTED_DEVICES},
    )


async def setup_entry(hass: HomeAssistant, entry: MockConfigEntry) -> None:
    """Add and set up a config entry."""
    entry.add_to_hass(hass)
    await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
