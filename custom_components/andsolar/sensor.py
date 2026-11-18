"""Sensors for AndSolar plants and devices."""

from __future__ import annotations

from dataclasses import dataclass

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorEntityDescription,
    SensorStateClass,
)
from homeassistant.const import (
    UnitOfElectricCurrent,
    UnitOfElectricPotential,
    UnitOfEnergy,
    UnitOfPower,
    UnitOfTemperature,
)
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN
from .coordinator import AndSolarConfigEntry, AndSolarCoordinator
from .entity import AndSolarDeviceEntity, plant_device_info
from .parsing import RAPID_SHUTDOWN, branch_value, branches_for, to_float

STATUS_OPTIONS = ["offline", "warning", "accident", "healthy"]

# kind -> (unit, device class, state class)
_KINDS = {
    "power": (UnitOfPower.WATT, SensorDeviceClass.POWER, SensorStateClass.MEASUREMENT),
    "voltage": (
        UnitOfElectricPotential.VOLT,
        SensorDeviceClass.VOLTAGE,
        SensorStateClass.MEASUREMENT,
    ),
    "current": (
        UnitOfElectricCurrent.AMPERE,
        SensorDeviceClass.CURRENT,
        SensorStateClass.MEASUREMENT,
    ),
    "temperature": (
        UnitOfTemperature.CELSIUS,
        SensorDeviceClass.TEMPERATURE,
        SensorStateClass.MEASUREMENT,
    ),
    "energy": (
        UnitOfEnergy.KILO_WATT_HOUR,
        SensorDeviceClass.ENERGY,
        SensorStateClass.TOTAL_INCREASING,
    ),
}

# (API field, label, kind)
_RAPID_SHUTDOWN_FIELDS = (
    ("totalOutputPower", "power", "power"),
    ("voltage", "voltage", "voltage"),
    ("current", "current", "current"),
    ("temperature", "temperature", "temperature"),
    ("dailyPowerGeneration", "daily energy", "energy"),
    ("totalGeneration", "total energy", "energy"),
)
_OPTIMIZER_FIELDS = (
    ("totalOutputPower", "output power", "power"),
    ("outputVoltage", "output voltage", "voltage"),
    ("outputCurrent", "output current", "current"),
    ("inputVoltage", "input voltage", "voltage"),
    ("inputCurrent", "input current", "current"),
    ("outputTemperature", "output temperature", "temperature"),
    ("inputTemperature", "input temperature", "temperature"),
    ("pcbTemperature", "PCB temperature", "temperature"),
    ("dailyPowerGeneration", "daily energy", "energy"),
    ("totalGeneration", "total energy", "energy"),
)


@dataclass(frozen=True, kw_only=True)
class AndSolarSensorDescription(SensorEntityDescription):
    """Which value of the API payload a sensor shows."""

    field: str
    branch: str | None = None  # None for plant sensors


PLANT_SENSORS = (
    AndSolarSensorDescription(
        key="plant_daily_energy",
        field="dailyEnergy",
        name="Daily energy",
        native_unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
        device_class=SensorDeviceClass.ENERGY,
        state_class=SensorStateClass.TOTAL_INCREASING,
    ),
    AndSolarSensorDescription(
        key="plant_total_energy",
        field="totalEnergy",
        name="Total energy",
        native_unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
        device_class=SensorDeviceClass.ENERGY,
        state_class=SensorStateClass.TOTAL_INCREASING,
    ),
)


def _cap(text: str) -> str:
    return text[:1].upper() + text[1:]


def device_descriptions(
    device_type: str | None, branch_num: int
) -> list[AndSolarSensorDescription]:
    """Sensors for one device, one set per branch."""
    is_rapid = device_type == RAPID_SHUTDOWN
    fields = _RAPID_SHUTDOWN_FIELDS if is_rapid else _OPTIMIZER_FIELDS
    descriptions: list[AndSolarSensorDescription] = []
    for index, branch in enumerate(branches_for(device_type, branch_num), start=1):
        prefix = f"Branch {index} " if is_rapid else ""
        for api_field, label, kind in fields:
            unit, device_class, state_class = _KINDS[kind]
            descriptions.append(
                AndSolarSensorDescription(
                    key=f"{branch}_{api_field}",
                    field=api_field,
                    branch=branch,
                    name=_cap(f"{prefix}{label}"),
                    native_unit_of_measurement=unit,
                    device_class=device_class,
                    state_class=state_class,
                )
            )
        descriptions.append(
            AndSolarSensorDescription(
                key=f"{branch}_deviceStatus",
                field="deviceStatus",
                branch=branch,
                name=_cap(f"{prefix}status"),
                device_class=SensorDeviceClass.ENUM,
                options=STATUS_OPTIONS,
            )
        )
    return descriptions


async def async_setup_entry(
    hass: HomeAssistant,
    entry: AndSolarConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Create sensors, and add more when new plants/devices show up."""
    coordinator = entry.runtime_data
    known: set[str] = set()

    @callback
    def _discover() -> None:
        new: list[SensorEntity] = []
        for plant_id in coordinator.data.plants:
            for description in PLANT_SENSORS:
                entity = AndSolarPlantSensor(coordinator, plant_id, description)
                if entity.unique_id not in known:
                    known.add(entity.unique_id)
                    new.append(entity)
        for sn, device in coordinator.data.devices.items():
            for description in device_descriptions(device.get("type"), device["branch_num"]):
                entity = AndSolarDeviceSensor(coordinator, sn, description)
                if entity.unique_id not in known:
                    known.add(entity.unique_id)
                    new.append(entity)
        if new:
            async_add_entities(new)

    _discover()
    entry.async_on_unload(coordinator.async_add_listener(_discover))


class AndSolarPlantSensor(CoordinatorEntity[AndSolarCoordinator], SensorEntity):
    """A plant-level value (daily / total energy)."""

    _attr_has_entity_name = True
    entity_description: AndSolarSensorDescription

    def __init__(
        self,
        coordinator: AndSolarCoordinator,
        plant_id: int,
        description: AndSolarSensorDescription,
    ) -> None:
        super().__init__(coordinator)
        self.entity_description = description
        self._plant_id = plant_id
        self._attr_unique_id = f"{DOMAIN}_plant_{plant_id}_{description.key}"
        plant = coordinator.data.plants.get(plant_id, {})
        self._attr_device_info = plant_device_info(plant_id, plant.get("name"))

    @property
    def available(self) -> bool:
        return super().available and self._plant_id in self.coordinator.data.plants

    @property
    def native_value(self) -> float | None:
        plant = self.coordinator.data.plants.get(self._plant_id)
        if not plant:
            return None
        return to_float(plant.get(self.entity_description.field))


class AndSolarDeviceSensor(AndSolarDeviceEntity, SensorEntity):
    """One value of one branch of a rapid shutdown device or optimizer."""

    entity_description: AndSolarSensorDescription

    def __init__(
        self,
        coordinator: AndSolarCoordinator,
        sn: str,
        description: AndSolarSensorDescription,
    ) -> None:
        super().__init__(coordinator, sn)
        self.entity_description = description
        self._attr_unique_id = f"{DOMAIN}_{sn}_{description.key}"

    @property
    def native_value(self) -> float | str | None:
        description = self.entity_description
        value = branch_value(self._latest, description.branch, description.field)
        if value is None:
            return None
        if description.device_class == SensorDeviceClass.ENUM:
            text = str(value).lower()
            return text if text in STATUS_OPTIONS else None
        return to_float(value)
