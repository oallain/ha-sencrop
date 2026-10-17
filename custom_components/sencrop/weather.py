"""Weather platform for the Sencrop integration."""

from datetime import timedelta

from homeassistant.components.weather import ATTR_CONDITION_RAINY, WeatherEntity
from homeassistant.const import UnitOfSpeed, UnitOfTemperature
from homeassistant.core import HomeAssistant
from homeassistant.helpers.device_registry import DeviceEntryType, DeviceInfo
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity
from homeassistant.util import dt as dt_util

from .const import DOMAIN, STALE_AFTER
from .coordinator import DeviceData, SencropConfigEntry, SencropCoordinator
from .derived import dew_point, is_stale, sum_since


async def async_setup_entry(
    hass: HomeAssistant,
    entry: SencropConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up the Sencrop weather entity."""
    async_add_entities([SencropWeather(entry.runtime_data, str(entry.unique_id))])


class SencropWeather(CoordinatorEntity[SencropCoordinator], WeatherEntity):
    """Current conditions combined from the selected Sencrop devices."""

    _attr_has_entity_name = True
    _attr_name = None
    _attr_native_temperature_unit = UnitOfTemperature.CELSIUS
    _attr_native_wind_speed_unit = UnitOfSpeed.KILOMETERS_PER_HOUR

    def __init__(self, coordinator: SencropCoordinator, user_id: str) -> None:
        """Initialize the weather entity."""
        super().__init__(coordinator)
        self._attr_unique_id = f"station_{user_id}"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, f"station_{user_id}")},
            manufacturer="Sencrop",
            name="Station Sencrop",
            entry_type=DeviceEntryType.SERVICE,
        )

    def _fresh_devices(self) -> list[DeviceData]:
        """Devices still reporting, in API order."""
        now = dt_util.utcnow()
        return [
            data
            for data in self.coordinator.data.values()
            if not is_stale(data.latest, now, STALE_AFTER)
        ]

    def _value(self, *measures: str) -> list[float] | None:
        """Values of the first fresh device reporting all the measures."""
        for data in self._fresh_devices():
            if all(m in data.latest for m in measures):
                return [data.latest[m].value for m in measures]
        return None

    def _first(self, measure: str) -> float | None:
        values = self._value(measure)
        return values[0] if values else None

    @property
    def available(self) -> bool:
        """Return False when no fresh device reports a temperature."""
        return super().available and self._first("TEMPERATURE") is not None

    @property
    def native_temperature(self) -> float | None:
        """Return the temperature."""
        return self._first("TEMPERATURE")

    @property
    def humidity(self) -> float | None:
        """Return the relative humidity."""
        return self._first("RELATIVE_HUMIDITY")

    @property
    def native_dew_point(self) -> float | None:
        """Return the dew point, from a device measuring both inputs."""
        values = self._value("TEMPERATURE", "RELATIVE_HUMIDITY")
        return dew_point(*values) if values else None

    @property
    def native_wind_speed(self) -> float | None:
        """Return the wind speed."""
        return self._first("WIND_SPEED")

    @property
    def native_wind_gust_speed(self) -> float | None:
        """Return the wind gust speed."""
        return self._first("WIND_GUST")

    @property
    def wind_bearing(self) -> float | None:
        """Return the wind direction."""
        return self._first("WIND_DIRECTION")

    @property
    def condition(self) -> str | None:
        """Return rainy when it rained during the last hour, else unknown."""
        now = dt_util.utcnow()
        since = now.replace(minute=0, second=0, microsecond=0) - timedelta(hours=1)
        for data in self._fresh_devices():
            if "RAIN_FALL" in data.device.measures:
                rain = sum_since(data.hourly, "RAIN_FALL", since)
                return ATTR_CONDITION_RAINY if rain else None
        return None
