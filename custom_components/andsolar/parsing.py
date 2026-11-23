"""Pure helpers with no Home Assistant imports, so they can be unit-tested alone."""

from __future__ import annotations

import json
import math
from typing import Any

RAPID_SHUTDOWN = "rapidShutdown"
MODULE_OPTIMIZER = "moduleOptimizer"
BRANCH_ONE = "branchOne"
BRANCH_TWO = "branchTwo"

STATUS_VALUES = ("offline", "warning", "accident", "healthy")

_METERS_PER_DEG_LAT = 110574.0
_METERS_PER_DEG_LON = 111320.0


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


def branch_key_for_index(branch: Any) -> tuple[int, str]:
    """Map an API branch number (1 or 2) to (index, branchKey)."""
    try:
        idx = int(branch)
    except (TypeError, ValueError):
        idx = 1
    if idx == 2:
        return 2, BRANCH_TWO
    return 1, BRANCH_ONE


def effective_branch_key(
    device_type: str | None,
    branch: Any,
    branch_num: int | None = None,
) -> tuple[int, str]:
    """Resolve the reporting branch key for a panel.

    Module optimizers (including 1:2 dual-panel optimizers) and single-branch
    rapid shutdown devices always report all measurements on ``branchOne``.
    """
    idx, key = branch_key_for_index(branch)
    if device_type == MODULE_OPTIMIZER:
        return idx, BRANCH_ONE
    if device_type == RAPID_SHUTDOWN and branch_num is not None and branch_num < 2:
        return idx, BRANCH_ONE
    return idx, key


def annotate_shared_panels(panels: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Annotate panels that share the same measurement source (e.g. 1:2 optimizer).

    Sets ``shared_count`` (total panels sharing ``(sn, branch_key)``) and
    ``shared_index`` (0-based deterministic index, ordered by branch then id).
    """
    groups: dict[tuple[str, str], list[dict[str, Any]]] = {}
    for panel in panels:
        group_key = (str(panel["sn"]), str(panel["branch_key"]))
        groups.setdefault(group_key, []).append(panel)

    for members in groups.values():
        count = len(members)
        ordered = sorted(
            members,
            key=lambda p: (
                int(p.get("branch") or 1),
                int(p["id"]) if p.get("id") is not None else 0,
            ),
        )
        for index, member in enumerate(ordered):
            member["shared_count"] = count
            member["shared_index"] = index
    return panels


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


def extract_polygon_coords(position: Any) -> list[tuple[float, float]] | None:
    """Extract outer ring [(lon, lat), ...] from a GeoJSON Feature/Polygon string or dict."""
    if not position:
        return None
    obj = position
    if isinstance(obj, str):
        try:
            obj = json.loads(obj)
        except ValueError:
            return None
    if not isinstance(obj, dict):
        return None

    geom = obj.get("geometry") if obj.get("type") == "Feature" else obj
    if not isinstance(geom, dict):
        return None

    geom_type = geom.get("type")
    coords = geom.get("coordinates")
    ring: Any = None
    if geom_type == "Polygon" and isinstance(coords, list) and coords:
        ring = coords[0]
    elif (
        geom_type == "MultiPolygon"
        and isinstance(coords, list)
        and coords
        and isinstance(coords[0], list)
        and coords[0]
    ):
        ring = coords[0][0]
    if not isinstance(ring, list):
        return None

    parsed: list[tuple[float, float]] = []
    for pt in ring:
        if not isinstance(pt, (list, tuple)) or len(pt) < 2:
            continue
        lon = to_float(pt[0])
        lat = to_float(pt[1])
        if lon is None or lat is None:
            continue
        parsed.append((lon, lat))

    if len(parsed) >= 4:
        first, last = parsed[0], parsed[-1]
        if abs(first[0] - last[0]) < 1e-12 and abs(first[1] - last[1]) < 1e-12:
            parsed.pop()

    return parsed if len(parsed) >= 3 else None


def parse_plant_layout(
    plant_id: int, modules: list[dict[str, Any]] | None
) -> list[dict[str, Any]]:
    """Parse /module/getViewListNoData into local 2D meter polygons (north-up, origin 0,0)."""
    raw_items: list[tuple[dict[str, Any], list[tuple[float, float]]]] = []
    all_lons: list[float] = []
    all_lats: list[float] = []

    for mod in modules or []:
        if not isinstance(mod, dict):
            continue
        sn = mod.get("deviceSn")
        if not sn:
            continue
        ring = extract_polygon_coords(mod.get("position"))
        if not ring:
            continue
        raw_items.append((mod, ring))
        for lon, lat in ring:
            all_lons.append(lon)
            all_lats.append(lat)

    if not raw_items:
        return []

    min_lon = min(all_lons)
    max_lat = max(all_lats)
    mean_lat = sum(all_lats) / len(all_lats)
    lon_scale = _METERS_PER_DEG_LON * math.cos(math.radians(mean_lat))

    panels: list[dict[str, Any]] = []
    for mod, ring in raw_items:
        device_type = mod.get("deviceType")
        branch_index, branch_key = effective_branch_key(device_type, mod.get("branch"))
        points = [
            [
                round((lon - min_lon) * lon_scale, 4),
                round((max_lat - lat) * _METERS_PER_DEG_LAT, 4),
            ]
            for lon, lat in ring
        ]
        panels.append(
            {
                "id": mod.get("id"),
                "plant_id": plant_id,
                "sn": str(mod["deviceSn"]),
                "device_id": mod.get("deviceId"),
                "collector_sn": mod.get("collectorSn"),
                "device_type": device_type,
                "branch": branch_index,
                "branch_key": branch_key,
                "rated_power": to_float(mod.get("power")),
                "points": points,
            }
        )
    return annotate_shared_panels(panels)


def layout_bounds(panels: list[dict[str, Any]]) -> dict[str, float]:
    """Return {width, height} in meters for parsed panels."""
    max_x = 0.0
    max_y = 0.0
    for panel in panels:
        for pt in panel.get("points") or []:
            if len(pt) >= 2:
                if pt[0] > max_x:
                    max_x = float(pt[0])
                if pt[1] > max_y:
                    max_y = float(pt[1])
    return {"width": round(max_x, 4), "height": round(max_y, 4)}


def _first_float(latest: Any, branch_key: str, fields: tuple[str, ...]) -> float | None:
    for field in fields:
        val = to_float(branch_value(latest, branch_key, field))
        if val is not None:
            return val
    return None


def panel_metrics(latest: Any, device_type: str | None, branch_key: str) -> dict[str, Any]:
    """Extract live metrics and derived display status for one panel branch."""
    is_rapid = device_type == RAPID_SHUTDOWN
    voltage_fields = (
        ("voltage", "outputVoltage", "inputVoltage")
        if is_rapid
        else ("outputVoltage", "voltage", "inputVoltage")
    )
    current_fields = (
        ("current", "outputCurrent", "inputCurrent")
        if is_rapid
        else ("outputCurrent", "current", "inputCurrent")
    )
    temp_fields = (
        ("temperature", "outputTemperature", "pcbTemperature")
        if is_rapid
        else ("outputTemperature", "pcbTemperature", "temperature", "inputTemperature")
    )

    values = {
        "daily_energy": _first_float(latest, branch_key, ("dailyPowerGeneration",)),
        "total_energy": _first_float(latest, branch_key, ("totalGeneration",)),
        "power": _first_float(latest, branch_key, ("totalOutputPower",)),
        "voltage": _first_float(latest, branch_key, voltage_fields),
        "current": _first_float(latest, branch_key, current_fields),
        "temperature": _first_float(latest, branch_key, temp_fields),
    }

    mos = mos_state(latest, branch_key)
    raw_status = branch_value(latest, branch_key, "deviceStatus")
    device_status = None
    if raw_status is not None:
        lowered = str(raw_status).lower()
        if lowered in STATUS_VALUES:
            device_status = lowered

    if latest is None or device_status == "offline":
        status = "offline"
    elif device_status in ("warning", "accident"):
        status = "warning"
    elif mos is False:
        status = "off"
    elif mos is True or device_status == "healthy":
        status = "on"
    else:
        status = "unknown"

    return {
        "values": values,
        "mos": mos,
        "device_status": device_status,
        "status": status,
    }


def panel_entity_unique_ids(
    domain: str, sn: str, device_type: str | None, branch_key: str
) -> dict[str, tuple[str, str]]:
    """Map panel metric/control keys to (platform, unique_id) matching sensor.py & switch.py."""
    is_rapid = device_type == RAPID_SHUTDOWN
    voltage_field = "voltage" if is_rapid else "outputVoltage"
    current_field = "current" if is_rapid else "outputCurrent"
    temp_field = "temperature" if is_rapid else "outputTemperature"

    return {
        "daily_energy": ("sensor", f"{domain}_{sn}_{branch_key}_dailyPowerGeneration"),
        "total_energy": ("sensor", f"{domain}_{sn}_{branch_key}_totalGeneration"),
        "power": ("sensor", f"{domain}_{sn}_{branch_key}_totalOutputPower"),
        "voltage": ("sensor", f"{domain}_{sn}_{branch_key}_{voltage_field}"),
        "current": ("sensor", f"{domain}_{sn}_{branch_key}_{current_field}"),
        "temperature": ("sensor", f"{domain}_{sn}_{branch_key}_{temp_field}"),
        "status": ("sensor", f"{domain}_{sn}_{branch_key}_deviceStatus"),
        "switch": ("switch", f"{domain}_{sn}_{branch_key}_switch"),
    }

