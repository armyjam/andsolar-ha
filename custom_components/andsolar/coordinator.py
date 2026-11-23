"""DataUpdateCoordinator for AndSolar."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from datetime import timedelta
import logging
import time
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .api import AndSolarClient, AndSolarError, ApiError, AuthError
from .const import DOMAIN, MAX_WORKERS, TOPOLOGY_REFRESH
from .parsing import parse_plant_layout, parse_topology

_LOGGER = logging.getLogger(__name__)

type AndSolarConfigEntry = ConfigEntry[AndSolarCoordinator]


@dataclass
class AndSolarData:
    """Everything the entities read."""

    # plant_id -> plant dict from /plant/queryList
    plants: dict[int, dict[str, Any]] = field(default_factory=dict)
    # serial number -> device info plus "latest" (latestData payload or None)
    devices: dict[str, dict[str, Any]] = field(default_factory=dict)
    # plant_id -> parsed panel polygons from /module/getViewListNoData
    layouts: dict[int, list[dict[str, Any]]] = field(default_factory=dict)


class AndSolarCoordinator(DataUpdateCoordinator[AndSolarData]):
    """Polls plants and the latest data of every device."""

    config_entry: AndSolarConfigEntry

    def __init__(
        self,
        hass: HomeAssistant,
        entry: AndSolarConfigEntry,
        client: AndSolarClient,
        interval_minutes: int,
    ) -> None:
        super().__init__(
            hass,
            _LOGGER,
            config_entry=entry,
            name=DOMAIN,
            update_interval=timedelta(minutes=interval_minutes),
        )
        self.client = client
        self._topology: dict[int, list[dict[str, Any]]] = {}
        self._layouts: dict[int, list[dict[str, Any]]] = {}
        self._topology_at = 0.0
        self._topology_warned = False
        self._layout_warned = False

    async def _async_update_data(self) -> AndSolarData:
        try:
            return await self.hass.async_add_executor_job(self._fetch)
        except AuthError as err:
            raise ConfigEntryAuthFailed(str(err)) from err
        except AndSolarError as err:
            raise UpdateFailed(str(err)) from err

    # Everything below runs in an executor thread (the client is blocking).

    def _fetch(self) -> AndSolarData:
        plants: dict[int, dict[str, Any]] = {}
        for plant in self.client.list_plants() or []:
            if plant.get("id") is not None:
                plants[int(plant["id"])] = plant

        stale = time.monotonic() - self._topology_at > TOPOLOGY_REFRESH.total_seconds()
        if not self._topology or stale:
            self._refresh_topology(list(plants))

        devices: dict[str, dict[str, Any]] = {}
        for plant_id, plant_devices in self._topology.items():
            if plant_id not in plants:
                continue
            for device in plant_devices:
                devices[device["sn"]] = dict(device, latest=None)

        if devices:
            with ThreadPoolExecutor(max_workers=MAX_WORKERS) as pool:
                for sn, latest in zip(list(devices), pool.map(self._fetch_latest, list(devices))):
                    devices[sn]["latest"] = latest

        layouts = {
            plant_id: list(panels)
            for plant_id, panels in self._layouts.items()
            if plant_id in plants
        }

        return AndSolarData(plants=plants, devices=devices, layouts=layouts)

    def _refresh_topology(self, plant_ids: list[int]) -> None:
        topology: dict[int, list[dict[str, Any]]] = {}
        layouts: dict[int, list[dict[str, Any]]] = {}
        failed = False
        layout_failed = False
        for plant_id in plant_ids:
            try:
                groups = self.client.plant_string_devices(plant_id)
            except ApiError as err:
                failed = True
                groups = []
                log = _LOGGER.debug if self._topology_warned else _LOGGER.warning
                log("Could not read the device list of plant %s: %s", plant_id, err)
            topology[plant_id] = parse_topology(plant_id, groups)

            try:
                raw_view = self.client.get_plant_view(plant_id)
                layouts[plant_id] = parse_plant_layout(plant_id, raw_view)
            except ApiError as err:
                layout_failed = True
                layouts[plant_id] = list(self._layouts.get(plant_id, []))
                log = _LOGGER.debug if self._layout_warned else _LOGGER.warning
                log("Could not read the panel layout of plant %s: %s", plant_id, err)

        self._topology = topology
        self._layouts = layouts
        self._layout_warned = layout_failed
        if failed:
            # Retry on the next update instead of waiting for the cache to expire.
            self._topology_warned = True
            self._topology_at = 0.0
        else:
            self._topology_warned = False
            self._topology_at = time.monotonic()

    def _fetch_latest(self, sn: str) -> dict[str, Any] | None:
        try:
            return self.client.latest_device_data(sn)
        except ApiError as err:
            _LOGGER.debug("No latest data for %s: %s", sn, err)
            return None
