"""Constants for the Sencrop integration."""

from datetime import timedelta

from homeassistant.const import Platform

DOMAIN = "sencrop"

CONF_DEVICES = "devices"
CONF_SCAN_INTERVAL = "scan_interval"
DEFAULT_SCAN_INTERVAL = 5
MIN_SCAN_INTERVAL = 5
MAX_SCAN_INTERVAL = 60

AGGREGATES_MAX_AGE = timedelta(minutes=30)
STALE_AFTER = timedelta(hours=2)

PLATFORMS = [Platform.SENSOR, Platform.WEATHER]
