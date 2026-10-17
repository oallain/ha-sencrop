"""Tests for the Sencrop diagnostics."""

import json
from unittest.mock import AsyncMock

import pytest
from homeassistant.core import HomeAssistant
from pytest_homeassistant_custom_component.common import MockConfigEntry
from pytest_homeassistant_custom_component.components.diagnostics import (
    get_diagnostics_for_config_entry,
)
from pytest_homeassistant_custom_component.typing import ClientSessionGenerator

from .conftest import setup_entry


@pytest.mark.usefixtures("frozen_now")
async def test_diagnostics_redacted(
    hass: HomeAssistant,
    hass_client: ClientSessionGenerator,
    mock_client: AsyncMock,
    mock_config_entry: MockConfigEntry,
) -> None:
    await setup_entry(hass, mock_config_entry)

    result = await get_diagnostics_for_config_entry(
        hass, hass_client, mock_config_entry
    )

    dumped = json.dumps(result)
    for secret in ("user@example.com", "secret", "12345", "SERIAL-", "45.0"):
        assert secret not in dumped
    assert set(result["devices"]) == {"1005", "1011", "1012"}
    device = result["devices"]["1012"]
    assert device["device"]["name"] == "**REDACTED**"
    assert device["device"]["model"] == "Raincrop"
    assert device["latest"]["TEMPERATURE"]["value"] == 11.15
    assert device["daily"]
