"""Diagnostics support for the Sencrop integration."""

from dataclasses import asdict
from typing import Any

from homeassistant.components.diagnostics import async_redact_data
from homeassistant.const import CONF_EMAIL, CONF_PASSWORD
from homeassistant.core import HomeAssistant

from .coordinator import SencropConfigEntry

TO_REDACT = {
    CONF_EMAIL,
    CONF_PASSWORD,
    "title",
    "name",
    "unique_id",
    "serial",
    "latitude",
    "longitude",
}


async def async_get_config_entry_diagnostics(
    hass: HomeAssistant, entry: SencropConfigEntry
) -> dict[str, Any]:
    """Return diagnostics for a config entry."""
    devices = {
        str(device_id): asdict(data)
        for device_id, data in entry.runtime_data.data.items()
    }
    return {
        "entry": async_redact_data(entry.as_dict(), TO_REDACT),
        "devices": async_redact_data(devices, TO_REDACT),
    }
