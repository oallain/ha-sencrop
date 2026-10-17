"""Data update coordinator for the Sencrop integration."""

import logging
from dataclasses import dataclass
from datetime import datetime, timedelta

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed
from homeassistant.util import dt as dt_util

from .api import (
    AggregateBucket,
    Measurement,
    SencropAuthError,
    SencropClient,
    SencropConnectionError,
    SencropDevice,
    SencropResponseError,
)
from .const import (
    AGGREGATES_MAX_AGE,
    CONF_DEVICES,
    CONF_SCAN_INTERVAL,
    DEFAULT_SCAN_INTERVAL,
    DOMAIN,
)
from .derived import last_measurement_date

_LOGGER = logging.getLogger(__name__)

type SencropConfigEntry = ConfigEntry[SencropCoordinator]


@dataclass
class DeviceData:
    """Latest state of one Sencrop device."""

    device: SencropDevice
    latest: dict[str, Measurement]
    hourly: list[AggregateBucket]
    daily: list[AggregateBucket]
    aggregates_at: datetime | None


class SencropCoordinator(DataUpdateCoordinator[dict[int, DeviceData]]):
    """Poll the selected Sencrop devices of an account."""

    config_entry: SencropConfigEntry

    def __init__(
        self, hass: HomeAssistant, entry: SencropConfigEntry, client: SencropClient
    ) -> None:
        """Initialize the coordinator."""
        super().__init__(
            hass,
            _LOGGER,
            config_entry=entry,
            name=DOMAIN,
            update_interval=timedelta(
                minutes=entry.options.get(CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL)
            ),
        )
        self.client = client

    @property
    def selected_ids(self) -> list[int]:
        """Ids of the devices chosen by the user."""
        return [int(i) for i in self.config_entry.options.get(CONF_DEVICES, [])]

    async def _async_update_data(self) -> dict[int, DeviceData]:
        now = dt_util.utcnow()
        previous = self.data or {}
        selected = set(self.selected_ids)
        data: dict[int, DeviceData] = {}
        try:
            devices = await self.client.async_get_devices()
            for device_id, device in devices.items():
                if device_id not in selected:
                    continue
                try:
                    data[device_id] = await self._update_device(
                        device, previous.get(device_id), now
                    )
                except SencropResponseError as err:
                    _LOGGER.warning(
                        "Ignoring unexpected data for Sencrop device %s: %s",
                        device.name,
                        err,
                    )
                    if device_id in previous:
                        data[device_id] = previous[device_id]
        except SencropAuthError as err:
            raise ConfigEntryAuthFailed(str(err)) from err
        except (SencropConnectionError, SencropResponseError) as err:
            raise UpdateFailed(str(err)) from err
        return data

    async def _update_device(
        self, device: SencropDevice, previous: DeviceData | None, now: datetime
    ) -> DeviceData:
        latest = await self.client.async_get_latest(device.id, device.measures, now)
        if previous is None:
            hourly, daily, aggregates_at = [], [], None
        else:
            hourly, daily = previous.hourly, previous.daily
            aggregates_at = previous.aggregates_at

        if self._aggregates_outdated(latest, previous, aggregates_at, now):
            time_zone = self.hass.config.time_zone
            has_rain = "RAIN_FALL" in device.measures
            daily_measures = []
            if has_rain:
                hourly = await self.client.async_get_hourly(
                    device.id, ["RAIN_FALL"], 2, time_zone, now
                )
                daily_measures.append("RAIN_FALL")
            if "TEMPERATURE" in device.measures:
                daily_measures += ["TEMPERATURE_MIN", "TEMPERATURE_MAX"]
            if daily_measures:
                daily = await self.client.async_get_daily(
                    device.id, daily_measures, 7, time_zone, now
                )
            aggregates_at = now

        return DeviceData(device, latest, hourly, daily, aggregates_at)

    @staticmethod
    def _aggregates_outdated(
        latest: dict[str, Measurement],
        previous: DeviceData | None,
        aggregates_at: datetime | None,
        now: datetime,
    ) -> bool:
        if previous is None or aggregates_at is None:
            return True
        if now - aggregates_at >= AGGREGATES_MAX_AGE:
            return True
        last = last_measurement_date(latest)
        before = last_measurement_date(previous.latest)
        return last is not None and (before is None or last > before)
