"""Pure helpers with no Home Assistant imports, so they can be unit-tested alone."""

from __future__ import annotations

from typing import Any

RAPID_SHUTDOWN = "rapidShutdown"
MODULE_OPTIMIZER = "moduleOptimizer"
BRANCH_ONE = "branchOne"
BRANCH_TWO = "branchTwo"


def to_float(value: Any) -> float | None:
    """The API returns some numbers as strings (e.g. "4.43")."""
    if value is None or isinstance(value, bool):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def parse_topology(plant_id: int, groups: list[dict[str, Any]] | None) -> list[dict[str, Any]]:
    """Flatten the plantGroupStringTree response into a list of devices."""
    devices: list[dict[str, Any]] = []
    for group in groups or []:
        for dev in group.get("deviceList") or []:
            sn = dev.get("deviceSn")
            if not sn:
                continue
            devices.append(
                {
                    "sn": str(sn),
                    "plant_id": plant_id,
                    "type": dev.get("deviceType"),
                    "model": dev.get("modelType"),
                    "series": dev.get("series"),
                    "branch_num": int(dev.get("branchNum") or 1),
                    "inverter": group.get("inverterNumber"),
                    "string": group.get("groupNumber"),
                    "collector_sn": group.get("collectorSn"),
                }
            )
    return devices


def branches_for(device_type: str | None, branch_num: int) -> list[str]:
    """Rapid shutdown devices can have two branches; optimizers have one."""
    if device_type == RAPID_SHUTDOWN and branch_num >= 2:
        return [BRANCH_ONE, BRANCH_TWO]
    return [BRANCH_ONE]


def branch_value(latest: Any, branch: str, field: str) -> Any:
    """Read latest[branch][field], tolerating missing or odd data."""
    if not isinstance(latest, dict):
        return None
    branch_data = latest.get(branch)
    if not isinstance(branch_data, dict):
        return None
    return branch_data.get(field)


def mos_state(latest: Any, branch: str) -> bool | None:
    """Switch state of a rapid shutdown branch (mos 1 = on), or None if unknown."""
    value = branch_value(latest, branch, "mos")
    return None if value is None else bool(value)
