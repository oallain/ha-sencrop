"""Base entity for the Sencrop integration."""

from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN
from .coordinator import DeviceData, SencropCoordinator


class SencropEntity(CoordinatorEntity[SencropCoordinator]):
    """An entity attached to one Sencrop device."""

    _attr_has_entity_name = True

    def __init__(
        self, coordinator: SencropCoordinator, device_id: int, key: str
    ) -> None:
        """Initialize the entity."""
        super().__init__(coordinator)
        self._device_id = device_id
        self._attr_unique_id = f"{device_id}_{key}"
        device = coordinator.data[device_id].device
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, str(device_id))},
            manufacturer="Sencrop",
            name=device.name,
            model=device.model,
            serial_number=device.serial,
            sw_version=device.firmware,
        )

    @property
    def device_data(self) -> DeviceData | None:
        """Latest data of the device, if still reported."""
        return self.coordinator.data.get(self._device_id)

    @property
    def available(self) -> bool:
        """Return True when the device is still reported by the API."""
        return super().available and self.device_data is not None
