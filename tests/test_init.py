"""Tests for the Sencrop config entry setup."""

from datetime import timedelta
from unittest.mock import AsyncMock

import pytest
from homeassistant.config_entries import ConfigEntryState
from homeassistant.core import HomeAssistant
from homeassistant.helpers import device_registry as dr
from homeassistant.setup import async_setup_component
from pytest_homeassistant_custom_component.common import MockConfigEntry
from pytest_homeassistant_custom_component.typing import WebSocketGenerator

from custom_components.sencrop.api import SencropAuthError, SencropConnectionError
from custom_components.sencrop.const import CONF_DEVICES, CONF_SCAN_INTERVAL, DOMAIN

from .conftest import SELECTED_DEVICES, setup_entry

pytestmark = pytest.mark.usefixtures("frozen_now")


async def test_setup_and_unload(
    hass: HomeAssistant, mock_client: AsyncMock, mock_config_entry: MockConfigEntry
) -> None:
    await setup_entry(hass, mock_config_entry)

    assert mock_config_entry.state is ConfigEntryState.LOADED

    assert await hass.config_entries.async_unload(mock_config_entry.entry_id)
    await hass.async_block_till_done()
    assert mock_config_entry.state is ConfigEntryState.NOT_LOADED


async def test_setup_retry_on_connection_error(
    hass: HomeAssistant, mock_client: AsyncMock, mock_config_entry: MockConfigEntry
) -> None:
    mock_client.async_get_devices.side_effect = SencropConnectionError("down")

    await setup_entry(hass, mock_config_entry)

    assert mock_config_entry.state is ConfigEntryState.SETUP_RETRY


async def test_setup_auth_error(
    hass: HomeAssistant, mock_client: AsyncMock, mock_config_entry: MockConfigEntry
) -> None:
    mock_client.async_get_devices.side_effect = SencropAuthError

    await setup_entry(hass, mock_config_entry)

    assert mock_config_entry.state is ConfigEntryState.SETUP_ERROR


async def test_options_update_reloads(
    hass: HomeAssistant, mock_client: AsyncMock, mock_config_entry: MockConfigEntry
) -> None:
    await setup_entry(hass, mock_config_entry)

    hass.config_entries.async_update_entry(
        mock_config_entry,
        options={CONF_SCAN_INTERVAL: 15, CONF_DEVICES: SELECTED_DEVICES},
    )
    await hass.async_block_till_done()

    assert mock_config_entry.state is ConfigEntryState.LOADED
    assert mock_config_entry.runtime_data.update_interval == timedelta(minutes=15)


def _device_identifiers(hass: HomeAssistant, entry: MockConfigEntry) -> set[str]:
    registry = dr.async_get(hass)
    return {
        identifier
        for device in dr.async_entries_for_config_entry(registry, entry.entry_id)
        for domain, identifier in device.identifiers
        if domain == DOMAIN
    }


async def test_deselected_devices_are_removed(
    hass: HomeAssistant, mock_client: AsyncMock, mock_config_entry: MockConfigEntry
) -> None:
    await setup_entry(hass, mock_config_entry)
    assert _device_identifiers(hass, mock_config_entry) == {
        "1005",
        "1011",
        "1012",
        "station_12345",
    }

    hass.config_entries.async_update_entry(
        mock_config_entry, options={CONF_SCAN_INTERVAL: 5, CONF_DEVICES: ["1012"]}
    )
    await hass.async_block_till_done()

    assert _device_identifiers(hass, mock_config_entry) == {"1012", "station_12345"}


async def test_remove_config_entry_device(
    hass: HomeAssistant,
    hass_ws_client: WebSocketGenerator,
    mock_client: AsyncMock,
    mock_config_entry: MockConfigEntry,
) -> None:
    assert await async_setup_component(hass, "config", {})
    await setup_entry(hass, mock_config_entry)
    registry = dr.async_get(hass)
    active = registry.async_get_device_by_identifier(
        (DOMAIN, "1012"), mock_config_entry.entry_id
    )
    gone = registry.async_get_or_create(
        config_entry_id=mock_config_entry.entry_id, identifiers={(DOMAIN, "1005")}
    )
    # 1005 stays selected but is no longer reported by the account.
    devices = dict(mock_client.async_get_devices.return_value)
    del devices[1005]
    mock_client.async_get_devices.return_value = devices
    await mock_config_entry.runtime_data.async_refresh()
    client = await hass_ws_client(hass)

    for device, expected in ((active, False), (gone, True)):
        await client.send_json_auto_id(
            {
                "type": "config/device_registry/remove_config_entry",
                "config_entry_id": mock_config_entry.entry_id,
                "device_id": device.id,
            }
        )
        response = await client.receive_json()
        assert response["success"] is expected
