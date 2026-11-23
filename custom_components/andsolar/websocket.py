"""WebSocket API for serving AndSolar plant panel layouts to the frontend card."""

from __future__ import annotations

from typing import Any

import voluptuous as vol

from homeassistant.components import websocket_api
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers import entity_registry as er

from .const import DOMAIN
from .coordinator import AndSolarCoordinator
from .parsing import (
    annotate_shared_panels,
    effective_branch_key,
    layout_bounds,
    panel_entity_unique_ids,
    panel_metrics,
    to_float,
)


@callback
def async_register_websocket_commands(hass: HomeAssistant) -> None:
    """Register AndSolar WebSocket commands once."""
    websocket_api.async_register_command(hass, ws_get_plant_layout)


def _iter_coordinators(hass: HomeAssistant) -> list[AndSolarCoordinator]:
    coordinators: list[AndSolarCoordinator] = []
    for entry in hass.config_entries.async_entries(DOMAIN):
        coordinator = getattr(entry, "runtime_data", None)
        if coordinator is not None and coordinator.data is not None:
            coordinators.append(coordinator)
    return coordinators


@websocket_api.websocket_command(
    {
        vol.Required("type"): "andsolar/get_plant_layout",
        vol.Optional("plant_id"): vol.Coerce(int),
    }
)
@callback
def ws_get_plant_layout(
    hass: HomeAssistant,
    connection: websocket_api.ActiveConnection,
    msg: dict[str, Any],
) -> None:
    """Return panel layout geometry, live metrics, and HA entity IDs for a plant."""
    requested_id: int | None = msg.get("plant_id")
    coordinators = _iter_coordinators(hass)

    available_plants: list[dict[str, Any]] = []
    matched_coordinator: AndSolarCoordinator | None = None
    selected_plant_id: int | None = None
    first_with_layout: tuple[AndSolarCoordinator, int] | None = None
    first_any: tuple[AndSolarCoordinator, int] | None = None

    for coordinator in coordinators:
        data = coordinator.data
        for plant_id, plant in data.plants.items():
            available_plants.append(
                {
                    "id": plant_id,
                    "name": plant.get("name") or f"Plant {plant_id}",
                }
            )
            if first_any is None:
                first_any = (coordinator, plant_id)
            if first_with_layout is None and data.layouts.get(plant_id):
                first_with_layout = (coordinator, plant_id)
            if requested_id is not None and plant_id == requested_id:
                matched_coordinator = coordinator
                selected_plant_id = plant_id

    if requested_id is None:
        chosen = first_with_layout or first_any
        if chosen is not None:
            matched_coordinator, selected_plant_id = chosen

    if matched_coordinator is None or selected_plant_id is None:
        detail = (
            f"AndSolar plant {requested_id} not found."
            if requested_id is not None
            else "No AndSolar plants found."
        )
        connection.send_error(msg["id"], "not_found", detail)
        return

    data = matched_coordinator.data
    plant = data.plants[selected_plant_id]
    raw_panels = data.layouts.get(selected_plant_id, [])
    ent_reg = er.async_get(hass)

    plant_entities = {
        "daily_energy": ent_reg.async_get_entity_id(
            "sensor", DOMAIN, f"{DOMAIN}_plant_{selected_plant_id}_plant_daily_energy"
        ),
        "total_energy": ent_reg.async_get_entity_id(
            "sensor", DOMAIN, f"{DOMAIN}_plant_{selected_plant_id}_plant_total_energy"
        ),
        "switch": ent_reg.async_get_entity_id(
            "switch", DOMAIN, f"{DOMAIN}_plant_{selected_plant_id}_switch"
        ),
    }

    panels: list[dict[str, Any]] = []
    for panel in raw_panels:
        sn = panel["sn"]
        device = data.devices.get(sn)
        device_type = (device.get("type") if device else None) or panel.get("device_type")
        device_branch_num = device.get("branch_num") if device else None
        branch_index, branch_key = effective_branch_key(
            device_type, panel.get("branch"), device_branch_num
        )
        latest = device.get("latest") if device else None

        metrics = panel_metrics(latest, device_type, branch_key)
        uid_map = panel_entity_unique_ids(DOMAIN, sn, device_type, branch_key)
        entities = {
            key: ent_reg.async_get_entity_id(platform, DOMAIN, uid)
            for key, (platform, uid) in uid_map.items()
        }

        panels.append(
            {
                "id": panel.get("id"),
                "sn": sn,
                "branch": branch_index,
                "branch_key": branch_key,
                "device_type": device_type,
                "model": device.get("model") if device else None,
                "inverter": device.get("inverter") if device else None,
                "string": device.get("string") if device else None,
                "rated_power": panel.get("rated_power"),
                "points": panel["points"],
                "values": metrics["values"],
                "mos": metrics["mos"],
                "device_status": metrics["device_status"],
                "status": metrics["status"],
                "entities": entities,
            }
        )

    annotate_shared_panels(panels)

    connection.send_result(
        msg["id"],
        {
            "plant": {
                "id": selected_plant_id,
                "name": plant.get("name") or f"Plant {selected_plant_id}",
                "daily_energy": to_float(plant.get("dailyEnergy")),
                "total_energy": to_float(plant.get("totalEnergy")),
                "entities": plant_entities,
            },
            "plants": available_plants,
            "bounds": layout_bounds(raw_panels),
            "panels": panels,
        },
    )
