"""Constants for the AndSolar integration."""

from datetime import timedelta

from homeassistant.const import Platform

DOMAIN = "andsolar"
MANUFACTURER = "AndSolar"

CONF_BASE_URL = "base_url"
CONF_SCAN_INTERVAL = "scan_interval"  # minutes

DEFAULT_BASE_URL = "https://ap.andsolartech.com"
DEFAULT_SCAN_INTERVAL = 5

# The plant/string/device layout rarely changes, so it is cached.
TOPOLOGY_REFRESH = timedelta(hours=6)
# Parallel latestData requests per update.
MAX_WORKERS = 8

PLATFORMS = [Platform.SENSOR, Platform.SWITCH]
