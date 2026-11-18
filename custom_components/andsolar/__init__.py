"""The AndSolar integration."""

from __future__ import annotations

from homeassistant.const import CONF_PASSWORD, CONF_USERNAME
from homeassistant.core import HomeAssistant
from homeassistant.helpers import device_registry as dr

from .api import AndSolarClient
from .const import (
    CONF_BASE_URL,
    CONF_SCAN_INTERVAL,
    DEFAULT_BASE_URL,
    DEFAULT_SCAN_INTERVAL,
    DOMAIN,
    MANUFACTURER,
    PLATFORMS,
)
from .coordinator import AndSolarConfigEntry, AndSolarCoordinator


async def async_setup_entry(hass: HomeAssistant, entry: AndSolarConfigEntry) -> bool:
    """Set up AndSolar from a config entry."""
    client = AndSolarClient(
        entry.data[CONF_USERNAME],
        entry.data[CONF_PASSWORD],
        base_url=entry.data.get(CONF_BASE_URL, DEFAULT_BASE_URL),
    )
    interval = entry.options.get(CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL)
    coordinator = AndSolarCoordinator(hass, entry, client, interval)
    # Raises ConfigEntryAuthFailed (starts re-auth) or ConfigEntryNotReady on failure.
    await coordinator.async_config_entry_first_refresh()
    entry.runtime_data = coordinator

    # Create plant devices first so device entities can reference them (via_device).
    registry = dr.async_get(hass)
    for plant_id, plant in coordinator.data.plants.items():
        registry.async_get_or_create(
            config_entry_id=entry.entry_id,
            identifiers={(DOMAIN, f"plant_{plant_id}")},
            manufacturer=MANUFACTURER,
            name=plant.get("name") or f"Plant {plant_id}",
            model="Plant",
        )

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    entry.async_on_unload(entry.add_update_listener(_async_reload_on_update))
    return True


async def async_unload_entry(hass: HomeAssistant, entry: AndSolarConfigEntry) -> bool:
    """Unload a config entry."""
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)


async def _async_reload_on_update(hass: HomeAssistant, entry: AndSolarConfigEntry) -> None:
    """Reload when options (the polling interval) change."""
    await hass.config_entries.async_reload(entry.entry_id)
