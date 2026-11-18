"""Shared entity helpers."""

from __future__ import annotations

from typing import Any

from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN, MANUFACTURER
from .coordinator import AndSolarCoordinator


def plant_device_info(plant_id: int, name: str | None = None) -> DeviceInfo:
    return DeviceInfo(
        identifiers={(DOMAIN, f"plant_{plant_id}")},
        manufacturer=MANUFACTURER,
        name=name or f"Plant {plant_id}",
        model="Plant",
    )


def device_device_info(device: dict[str, Any]) -> DeviceInfo:
    model = device.get("model") or device.get("type") or "Device"
    return DeviceInfo(
        identifiers={(DOMAIN, device["sn"])},
        manufacturer=MANUFACTURER,
        name=f"{model} {device['sn']}",
        model=model,
        serial_number=device["sn"],
        via_device=(DOMAIN, f"plant_{device['plant_id']}"),
    )


class AndSolarDeviceEntity(CoordinatorEntity[AndSolarCoordinator]):
    """Base class for entities that belong to one rapid shutdown / optimizer."""

    _attr_has_entity_name = True

    def __init__(self, coordinator: AndSolarCoordinator, sn: str) -> None:
        super().__init__(coordinator)
        self._sn = sn
        self._attr_device_info = device_device_info(coordinator.data.devices[sn])

    @property
    def _device(self) -> dict[str, Any] | None:
        return self.coordinator.data.devices.get(self._sn)

    @property
    def _latest(self) -> dict[str, Any] | None:
        device = self._device
        return device.get("latest") if device else None

    @property
    def available(self) -> bool:
        return super().available and self._latest is not None
