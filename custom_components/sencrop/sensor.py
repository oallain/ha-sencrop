"""Sensor platform for the Sencrop integration."""

import logging
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from datetime import datetime, timedelta

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorEntityDescription,
    SensorStateClass,
)
from homeassistant.const import (
    DEGREE,
    PERCENTAGE,
    EntityCategory,
    UnitOfElectricPotential,
    UnitOfPrecipitationDepth,
    UnitOfSpeed,
    UnitOfTemperature,
)
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from homeassistant.helpers.typing import StateType
from homeassistant.util import dt as dt_util

from .api import SencropDevice
from .const import STALE_AFTER
from .coordinator import DeviceData, SencropConfigEntry, SencropCoordinator
from .derived import (
    daily_bucket,
    dew_point,
    is_stale,
    last_measurement_date,
    sum_days,
    sum_since,
    today_extreme,
)
from .entity import SencropEntity

_LOGGER = logging.getLogger(__name__)

LINK_QUALITIES = ["excellent", "good", "average", "limit", "unknown"]


@dataclass(frozen=True, kw_only=True)
class SencropSensorEntityDescription(SensorEntityDescription):
    """Describe a Sencrop sensor."""

    value_fn: Callable[[DeviceData, datetime], StateType | datetime]
    exists_fn: Callable[[SencropDevice], bool]
    requires_fresh_data: bool = True
    last_reset_fn: Callable[[datetime], datetime] | None = None


def _has(*measures: str) -> Callable[[SencropDevice], bool]:
    return lambda device: all(m in device.measures for m in measures)


def _latest(measure: str) -> Callable[[DeviceData, datetime], float | None]:
    def value(data: DeviceData, now: datetime) -> float | None:
        measurement = data.latest.get(measure)
        return measurement.value if measurement else None

    return value


def _today_temperature(
    measure: str, pick: Callable[[Iterable[float]], float]
) -> Callable[[DeviceData, datetime], float | None]:
    def value(data: DeviceData, now: datetime) -> float | None:
        current = data.latest.get("TEMPERATURE")
        return today_extreme(data.daily, measure, current, now, pick)

    return value


def _rain_today(data: DeviceData, now: datetime) -> float | None:
    bucket = daily_bucket(data.daily, now.date())
    return bucket.values.get("RAIN_FALL", 0.0) if bucket else None


def _rain_24h(data: DeviceData, now: datetime) -> float | None:
    # 24 hourly buckets: the current (partial) hour and the 23 before.
    current_hour = now.replace(minute=0, second=0, microsecond=0)
    return sum_since(data.hourly, "RAIN_FALL", current_hour - timedelta(hours=23))


def _rain_7d(data: DeviceData, now: datetime) -> float | None:
    return sum_days(data.daily, "RAIN_FALL", now.date() - timedelta(days=6))


def _dew_point(data: DeviceData, now: datetime) -> float | None:
    temperature = data.latest.get("TEMPERATURE")
    humidity = data.latest.get("RELATIVE_HUMIDITY")
    if temperature is None or humidity is None:
        return None
    return dew_point(temperature.value, humidity.value)


def _link_quality(data: DeviceData, now: datetime) -> str | None:
    quality = data.device.link_quality
    if quality is None:
        return None
    if quality not in LINK_QUALITIES:
        _LOGGER.debug("Unknown Sencrop link quality %s", quality)
        return "unknown"
    return quality


def _always(device: SencropDevice) -> bool:
    return True


def _temperature(key: str, value_fn, exists_fn) -> SencropSensorEntityDescription:
    return SencropSensorEntityDescription(
        key=key,
        translation_key=key,
        device_class=SensorDeviceClass.TEMPERATURE,
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement=UnitOfTemperature.CELSIUS,
        suggested_display_precision=1,
        value_fn=value_fn,
        exists_fn=exists_fn,
    )


def _precipitation(
    key: str, value_fn, state_class: SensorStateClass = SensorStateClass.MEASUREMENT
) -> SencropSensorEntityDescription:
    return SencropSensorEntityDescription(
        key=key,
        translation_key=key,
        device_class=SensorDeviceClass.PRECIPITATION,
        state_class=state_class,
        native_unit_of_measurement=UnitOfPrecipitationDepth.MILLIMETERS,
        suggested_display_precision=1,
        value_fn=value_fn,
        exists_fn=_has("RAIN_FALL"),
        last_reset_fn=(
            dt_util.start_of_local_day
            if state_class is SensorStateClass.TOTAL
            else None
        ),
    )


def _wind_speed(key: str, measure: str) -> SencropSensorEntityDescription:
    return SencropSensorEntityDescription(
        key=key,
        translation_key=key,
        device_class=SensorDeviceClass.WIND_SPEED,
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement=UnitOfSpeed.KILOMETERS_PER_HOUR,
        suggested_display_precision=1,
        value_fn=_latest(measure),
        exists_fn=_has(measure),
    )


SENSORS: tuple[SencropSensorEntityDescription, ...] = (
    _temperature("temperature", _latest("TEMPERATURE"), _has("TEMPERATURE")),
    SencropSensorEntityDescription(
        key="humidity",
        translation_key="humidity",
        device_class=SensorDeviceClass.HUMIDITY,
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement=PERCENTAGE,
        suggested_display_precision=0,
        value_fn=_latest("RELATIVE_HUMIDITY"),
        exists_fn=_has("RELATIVE_HUMIDITY"),
    ),
    _temperature(
        "wet_temperature", _latest("WET_TEMPERATURE"), _has("WET_TEMPERATURE")
    ),
    _wind_speed("wind_speed", "WIND_SPEED"),
    _wind_speed("wind_gust", "WIND_GUST"),
    SencropSensorEntityDescription(
        key="wind_direction",
        translation_key="wind_direction",
        device_class=SensorDeviceClass.WIND_DIRECTION,
        state_class=SensorStateClass.MEASUREMENT_ANGLE,
        native_unit_of_measurement=DEGREE,
        suggested_display_precision=0,
        value_fn=_latest("WIND_DIRECTION"),
        exists_fn=_has("WIND_DIRECTION"),
    ),
    _precipitation("rain", _latest("RAIN_FALL")),
    _precipitation("rain_today", _rain_today, SensorStateClass.TOTAL),
    _precipitation("rain_24h", _rain_24h),
    _precipitation("rain_7d", _rain_7d),
    _temperature(
        "temperature_min_today",
        _today_temperature("TEMPERATURE_MIN", min),
        _has("TEMPERATURE"),
    ),
    _temperature(
        "temperature_max_today",
        _today_temperature("TEMPERATURE_MAX", max),
        _has("TEMPERATURE"),
    ),
    _temperature("dew_point", _dew_point, _has("TEMPERATURE", "RELATIVE_HUMIDITY")),
    SencropSensorEntityDescription(
        key="battery_voltage",
        translation_key="battery_voltage",
        device_class=SensorDeviceClass.VOLTAGE,
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement=UnitOfElectricPotential.MILLIVOLT,
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda data, now: data.device.battery_mv,
        exists_fn=_always,
        requires_fresh_data=False,
    ),
    SencropSensorEntityDescription(
        key="link_quality",
        translation_key="link_quality",
        device_class=SensorDeviceClass.ENUM,
        options=LINK_QUALITIES,
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=_link_quality,
        exists_fn=_always,
        requires_fresh_data=False,
    ),
    SencropSensorEntityDescription(
        key="firmware",
        translation_key="firmware",
        entity_category=EntityCategory.DIAGNOSTIC,
        entity_registry_enabled_default=False,
        value_fn=lambda data, now: data.device.firmware,
        exists_fn=_always,
        requires_fresh_data=False,
    ),
    SencropSensorEntityDescription(
        key="last_measurement",
        translation_key="last_measurement",
        device_class=SensorDeviceClass.TIMESTAMP,
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda data, now: last_measurement_date(data.latest),
        exists_fn=_always,
        requires_fresh_data=False,
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: SencropConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up Sencrop sensors."""
    coordinator = entry.runtime_data
    async_add_entities(
        SencropSensor(coordinator, device_id, description)
        for device_id, data in coordinator.data.items()
        for description in SENSORS
        if description.exists_fn(data.device)
    )


class SencropSensor(SencropEntity, SensorEntity):
    """A Sencrop measure or derived value."""

    entity_description: SencropSensorEntityDescription

    def __init__(
        self,
        coordinator: SencropCoordinator,
        device_id: int,
        description: SencropSensorEntityDescription,
    ) -> None:
        """Initialize the sensor."""
        super().__init__(coordinator, device_id, description.key)
        self.entity_description = description

    @property
    def available(self) -> bool:
        """Return False when the device stopped reporting."""
        if not super().available:
            return False
        if not self.entity_description.requires_fresh_data:
            return True
        data = self.device_data
        return data is not None and not is_stale(
            data.latest, dt_util.utcnow(), STALE_AFTER
        )

    @property
    def native_value(self) -> StateType | datetime:
        """Return the sensor value."""
        data = self.device_data
        if data is None:
            return None
        return self.entity_description.value_fn(data, dt_util.now())

    @property
    def last_reset(self) -> datetime | None:
        """Return the start of the accumulation period."""
        if (reset_fn := self.entity_description.last_reset_fn) is None:
            return None
        return reset_fn(dt_util.now())
