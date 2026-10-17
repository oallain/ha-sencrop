"""The Sencrop integration."""

from homeassistant.const import CONF_EMAIL, CONF_PASSWORD
from homeassistant.core import HomeAssistant
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .api import SencropClient
from .const import DOMAIN, PLATFORMS
from .coordinator import SencropConfigEntry, SencropCoordinator


async def async_setup_entry(hass: HomeAssistant, entry: SencropConfigEntry) -> bool:
    """Set up Sencrop from a config entry."""
    client = SencropClient(
        async_get_clientsession(hass), entry.data[CONF_EMAIL], entry.data[CONF_PASSWORD]
    )
    coordinator = SencropCoordinator(hass, entry, client)
    await coordinator.async_config_entry_first_refresh()
    entry.runtime_data = coordinator
    _async_remove_deselected_devices(hass, entry, coordinator)

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    entry.async_on_unload(entry.add_update_listener(_async_update_listener))
    return True


async def async_unload_entry(hass: HomeAssistant, entry: SencropConfigEntry) -> bool:
    """Unload a config entry."""
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)


async def _async_update_listener(
    hass: HomeAssistant, entry: SencropConfigEntry
) -> None:
    """Reload the entry when its options change."""
    await hass.config_entries.async_reload(entry.entry_id)


def _async_remove_deselected_devices(
    hass: HomeAssistant, entry: SencropConfigEntry, coordinator: SencropCoordinator
) -> None:
    """Remove the devices the user no longer selects."""
    keep = {str(device_id) for device_id in coordinator.selected_ids}
    keep.add(f"station_{entry.unique_id}")
    registry = dr.async_get(hass)
    for device in dr.async_entries_for_config_entry(registry, entry.entry_id):
        if not any(
            domain == DOMAIN and identifier in keep
            for domain, identifier in device.identifiers
        ):
            registry.async_update_device(
                device.id, remove_config_entry_id=entry.entry_id
            )


async def async_remove_config_entry_device(
    hass: HomeAssistant, entry: SencropConfigEntry, device: dr.DeviceEntry
) -> bool:
    """Allow removing a device that the account no longer reports."""
    reported = {str(device_id) for device_id in entry.runtime_data.data}
    reported.add(f"station_{entry.unique_id}")
    return not any(
        domain == DOMAIN and identifier in reported
        for domain, identifier in device.identifiers
    )
