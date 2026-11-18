"""Switches: plant-wide output and per-device / per-branch output."""

from __future__ import annotations

from typing import Any

from homeassistant.components.switch import SwitchDeviceClass, SwitchEntity
from homeassistant.core import HomeAssistant, callback
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.restore_state import RestoreEntity
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .api import AndSolarError
from .const import DOMAIN
from .coordinator import AndSolarConfigEntry, AndSolarCoordinator
from .entity import AndSolarDeviceEntity, plant_device_info
from .parsing import BRANCH_ONE, BRANCH_TWO, RAPID_SHUTDOWN, branches_for, mos_state


async def async_setup_entry(
    hass: HomeAssistant,
    entry: AndSolarConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Create switches, and add more when new plants/devices show up."""
    coordinator = entry.runtime_data
    known: set[str] = set()

    @callback
    def _discover() -> None:
        new: list[SwitchEntity] = []
        for plant_id in coordinator.data.plants:
            entity: SwitchEntity = AndSolarPlantSwitch(coordinator, plant_id)
            if entity.unique_id not in known:
                known.add(entity.unique_id)
                new.append(entity)
        for sn, device in coordinator.data.devices.items():
            branches = branches_for(device.get("type"), device["branch_num"])
            for index, branch in enumerate(branches, start=1):
                entity = AndSolarDeviceSwitch(coordinator, sn, branch, index)
                if entity.unique_id not in known:
                    known.add(entity.unique_id)
                    new.append(entity)
        if new:
            async_add_entities(new)

    _discover()
    entry.async_on_unload(coordinator.async_add_listener(_discover))


class AndSolarPlantSwitch(CoordinatorEntity[AndSolarCoordinator], SwitchEntity, RestoreEntity):
    """Switch every rapid shutdown device of a plant on or off.

    The API has no way to read this state back, so it is assumed from the last
    command. Disabled by default because it affects a whole plant.
    """

    _attr_has_entity_name = True
    _attr_name = "Plant output"
    _attr_device_class = SwitchDeviceClass.SWITCH
    _attr_assumed_state = True
    _attr_entity_registry_enabled_default = False

    def __init__(self, coordinator: AndSolarCoordinator, plant_id: int) -> None:
        super().__init__(coordinator)
        self._plant_id = plant_id
        self._is_on: bool | None = None
        self._attr_unique_id = f"{DOMAIN}_plant_{plant_id}_switch"
        plant = coordinator.data.plants.get(plant_id, {})
        self._attr_device_info = plant_device_info(plant_id, plant.get("name"))

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        last = await self.async_get_last_state()
        if last is not None and last.state in ("on", "off"):
            self._is_on = last.state == "on"

    @property
    def is_on(self) -> bool | None:
        return self._is_on

    async def async_turn_on(self, **kwargs: Any) -> None:
        await self._set(True)

    async def async_turn_off(self, **kwargs: Any) -> None:
        await self._set(False)

    def _run(self, on: bool) -> dict[str, str]:
        client = self.coordinator.client
        task = client.plant_switch(self._plant_id, on)
        return client.wait_for_plant_switch(self._plant_id, task, timeout=120)

    async def _set(self, on: bool) -> None:
        try:
            result = await self.hass.async_add_executor_job(self._run, on)
        except (AndSolarError, TimeoutError) as err:
            raise HomeAssistantError(f"Plant switch command failed: {err}") from err
        failed = sorted(sn for sn, status in result.items() if status != "TRUE")
        if failed:
            raise HomeAssistantError(
                f"{len(failed)} device(s) did not confirm the command: {', '.join(failed)}"
            )
        self._is_on = on
        self.async_write_ha_state()
        await self.coordinator.async_request_refresh()


class AndSolarDeviceSwitch(AndSolarDeviceEntity, SwitchEntity, RestoreEntity):
    """Output switch of one branch of a device.

    Rapid shutdown devices report their switch state (``mos``). Module
    optimizers do not, so their state is assumed from the last command.
    """

    _attr_device_class = SwitchDeviceClass.SWITCH

    def __init__(
        self,
        coordinator: AndSolarCoordinator,
        sn: str,
        branch: str,
        index: int,
    ) -> None:
        super().__init__(coordinator, sn)
        device = coordinator.data.devices[sn]
        self._branch = branch
        self._device_type = device.get("type")
        self._is_rapid = self._device_type == RAPID_SHUTDOWN
        self._branch_count = len(branches_for(self._device_type, device["branch_num"]))
        self._optimistic: bool | None = None
        self._attr_assumed_state = not self._is_rapid
        self._attr_unique_id = f"{DOMAIN}_{sn}_{branch}_switch"
        self._attr_name = f"Branch {index} output" if self._branch_count > 1 else "Output"

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        if self._is_rapid:
            return
        last = await self.async_get_last_state()
        if last is not None and last.state in ("on", "off"):
            self._optimistic = last.state == "on"

    @property
    def is_on(self) -> bool | None:
        if self._is_rapid:
            return mos_state(self._latest, self._branch)
        return self._optimistic

    async def async_turn_on(self, **kwargs: Any) -> None:
        await self._set(True)

    async def async_turn_off(self, **kwargs: Any) -> None:
        await self._set(False)

    def _targets(self, on: bool) -> tuple[bool, bool | None]:
        """Rapid shutdown needs both switch values; keep the other branch as is."""
        if not self._is_rapid:
            return on, None
        if self._branch_count < 2:
            return on, on
        other_branch = BRANCH_TWO if self._branch == BRANCH_ONE else BRANCH_ONE
        other = mos_state(self._latest, other_branch)
        if other is None:
            raise HomeAssistantError(
                "State of the other branch is unknown; try again after the next update."
            )
        return (on, other) if self._branch == BRANCH_ONE else (other, on)

    async def _set(self, on: bool) -> None:
        switch1, switch2 = self._targets(on)
        try:
            ok = await self.hass.async_add_executor_job(
                self.coordinator.client.switch_device, self._sn, switch1, switch2
            )
        except AndSolarError as err:
            raise HomeAssistantError(f"Switch command failed: {err}") from err
        if ok is False:
            raise HomeAssistantError("The device rejected the switch command.")
        self._optimistic = on
        self.async_write_ha_state()
        await self.coordinator.async_request_refresh()
