"""Python client for the AndSolar OpenAPI.

Zero third-party dependencies (standard library only).

Flow implemented here, as described by the API docs:
  1. ``GET /api/openapi/login?username=...&password=...`` returns ``data.token``.
  2. Every business request carries ``Version: openapi`` and
     ``Authorization: Bearer {token}``.
  3. The token is valid for 7 days; the client caches it and re-logs-in
     automatically (once) when a request comes back 401.

Production host: https://ap.andsolartech.com
Test host:       https://monitor.andsolartech.com
"""

from __future__ import annotations

import json
import os
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from typing import Any, Dict, Iterator, List, Mapping, Optional, Sequence

__all__ = [
    "AndSolarClient",
    "AndSolarError",
    "ApiError",
    "AuthError",
    "DEFAULT_BASE_URL",
]

DEFAULT_BASE_URL = "https://ap.andsolartech.com"
API_PREFIX = "/api/openapi"

# Docs say the token lives 7 days. Refresh a day early to avoid edge cases.
_TOKEN_LIFETIME = 7 * 24 * 3600
_TOKEN_REFRESH_MARGIN = 24 * 3600

_USER_AGENT = "andsolar-openapi-python/0.1"


class AndSolarError(Exception):
    """Base class for all errors raised by this client."""


class AuthError(AndSolarError):
    """Login failed, or the token was rejected even after re-login."""


class ApiError(AndSolarError):
    """The server answered with an HTTP error or a non-200 ``code``."""

    def __init__(
        self,
        message: str,
        *,
        status: Optional[int] = None,
        code: Optional[int] = None,
        payload: Any = None,
    ) -> None:
        super().__init__(message)
        self.status = status
        self.code = code
        self.payload = payload


def _query_value(value: Any) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    return str(value)


class AndSolarClient:
    """Thin, typed-ish wrapper around the AndSolar OpenAPI.

    >>> client = AndSolarClient("user", "pass")          # production host
    >>> plants = client.list_plants()
    """

    def __init__(
        self,
        username: str,
        password: str,
        base_url: str = DEFAULT_BASE_URL,
        timeout: float = 30.0,
    ) -> None:
        if not username or not password:
            raise ValueError("username and password are required")
        self.username = username
        self._password = password
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        self._token: Optional[str] = None
        self._token_expires_at = 0.0
        self._lock = threading.Lock()

    @classmethod
    def from_env(cls, **kwargs: Any) -> "AndSolarClient":
        """Build a client from ANDSOLAR_USERNAME / ANDSOLAR_PASSWORD /
        ANDSOLAR_BASE_URL (optional) environment variables."""
        username = os.environ.get("ANDSOLAR_USERNAME", "")
        password = os.environ.get("ANDSOLAR_PASSWORD", "")
        base_url = os.environ.get("ANDSOLAR_BASE_URL", DEFAULT_BASE_URL)
        return cls(username, password, base_url=base_url, **kwargs)

    # ------------------------------------------------------------------ auth

    def login(self) -> str:
        """Log in, cache and return the token."""
        status, payload = self._send(
            "GET",
            "/login",
            params={"username": self.username, "password": self._password},
            token=None,
        )
        if status == 401 or (isinstance(payload, dict) and payload.get("code") == 401):
            raise AuthError("login rejected: invalid username or password")
        if status >= 400:
            raise ApiError(f"login failed with HTTP {status}", status=status, payload=payload)
        if isinstance(payload, dict) and payload.get("code") not in (None, 200):
            raise AuthError(f"login failed: {payload.get('msg')!r} (code {payload.get('code')})")
        token = None
        if isinstance(payload, dict) and isinstance(payload.get("data"), dict):
            token = payload["data"].get("token")
        if not token:
            raise AuthError("login response did not contain data.token")
        with self._lock:
            self._token = token
            self._token_expires_at = time.time() + _TOKEN_LIFETIME - _TOKEN_REFRESH_MARGIN
        return token

    def _get_token(self) -> str:
        with self._lock:
            if self._token and time.time() < self._token_expires_at:
                return self._token
        return self.login()

    def _invalidate_token(self) -> None:
        with self._lock:
            self._token = None
            self._token_expires_at = 0.0

    # ------------------------------------------------------------- transport

    def _send(
        self,
        method: str,
        path: str,
        *,
        params: Optional[Mapping[str, Any]] = None,
        body: Any = None,
        token: Optional[str],
    ) -> "tuple[int, Any]":
        url = self.base_url + API_PREFIX + path
        if params:
            query = {k: _query_value(v) for k, v in params.items() if v is not None}
            url += "?" + urllib.parse.urlencode(query)
        headers = {
            "Version": "openapi",
            "Accept": "application/json",
            "User-Agent": _USER_AGENT,
        }
        data = None
        if body is not None:
            data = json.dumps(body).encode("utf-8")
            headers["Content-Type"] = "application/json"
        if token:
            headers["Authorization"] = f"Bearer {token}"
        request = urllib.request.Request(url, data=data, method=method, headers=headers)
        try:
            with urllib.request.urlopen(request, timeout=self.timeout) as response:
                status, raw = response.status, response.read()
        except urllib.error.HTTPError as exc:
            status, raw = exc.code, exc.read()
        except urllib.error.URLError as exc:
            raise AndSolarError(f"network error calling {method} {path}: {exc.reason}") from exc
        text = raw.decode("utf-8", errors="replace")
        try:
            payload: Any = json.loads(text) if text else None
        except ValueError:
            payload = text
        return status, payload

    def _request(
        self,
        method: str,
        path: str,
        *,
        params: Optional[Mapping[str, Any]] = None,
        body: Any = None,
    ) -> Any:
        """Authenticated request. Re-logs-in once if the token is rejected."""
        status: int = 0
        payload: Any = None
        unauthorized = False
        for attempt in (1, 2):
            token = self._get_token()
            status, payload = self._send(method, path, params=params, body=body, token=token)
            unauthorized = status == 401 or (
                isinstance(payload, dict) and payload.get("code") == 401
            )
            if unauthorized and attempt == 1:
                self._invalidate_token()
                continue
            break
        if unauthorized:
            raise AuthError("token rejected (401) even after re-login")
        if status >= 400:
            raise ApiError(
                f"{method} {path} failed with HTTP {status}", status=status, payload=payload
            )
        if isinstance(payload, dict) and payload.get("code") not in (None, 200):
            raise ApiError(
                f"{method} {path} failed: {payload.get('msg')!r} (code {payload.get('code')})",
                status=status,
                code=payload.get("code"),
                payload=payload,
            )
        return payload

    @staticmethod
    def _data(payload: Any) -> Any:
        if isinstance(payload, dict) and "data" in payload:
            return payload["data"]
        return payload

    # ---------------------------------------------------------------- plants

    def list_plants(self) -> List[Dict[str, Any]]:
        """GET /plant/queryList"""
        return self._data(self._request("GET", "/plant/queryList"))

    def get_plant(self, plant_id: int) -> Dict[str, Any]:
        """GET /plant/getPlantInfo"""
        return self._data(self._request("GET", "/plant/getPlantInfo", params={"plantId": plant_id}))

    def add_plant(self, name: str, latitude: float, longitude: float) -> Dict[str, Any]:
        """POST /plant/add/v2"""
        body = {"name": name, "latitude": latitude, "longitude": longitude}
        return self._data(self._request("POST", "/plant/add/v2", body=body))

    def edit_plant(self, plant_id: int, name: str, latitude: float, longitude: float) -> bool:
        """POST /plant/edit"""
        body = {"id": plant_id, "name": name, "latitude": latitude, "longitude": longitude}
        return self._data(self._request("POST", "/plant/edit", body=body))

    def delete_plant(self, plant_id: int) -> bool:
        """DELETE /plant/delete/{plantId}"""
        return self._data(self._request("DELETE", f"/plant/delete/{int(plant_id)}"))

    def get_plant_view(self, plant_id: int) -> List[Dict[str, Any]]:
        """GET /module/getViewListNoData - module positions on the plant view."""
        return self._data(
            self._request("GET", "/module/getViewListNoData", params={"plantId": plant_id})
        )

    # ------------------------------------------------------------ gateways

    def list_collectors(self, plant_id: int) -> List[Dict[str, Any]]:
        """GET /col/queryList - gateways bound to a plant."""
        return self._data(self._request("GET", "/col/queryList", params={"plantId": plant_id}))

    def check_collector_sn(self, sn: str) -> Dict[str, Any]:
        """GET /col/check - returns ``{"passed": bool, "code"?: int, "msg"?: str}``.

        Failure codes: 4001 = bad SN format, 4002 = already bound to a plant.
        """
        return self._data(self._request("GET", "/col/check", params={"sn": sn}))

    def bind_collector(self, plant_id: int, col_sn: str, col_name: str) -> bool:
        """POST /col/add"""
        body = {"plantId": plant_id, "colSn": col_sn, "colName": col_name}
        return self._data(self._request("POST", "/col/add", body=body))

    def unbind_collector(self, plant_id: int, col_sn: str) -> bool:
        """POST /col/deleteCollector"""
        body = {"plantId": plant_id, "colSn": col_sn}
        return self._data(self._request("POST", "/col/deleteCollector", body=body))

    def set_collector_switch(self, plant_id: int, col_sn: str, heartbeat: bool) -> bool:
        """GET /col/switch - heartbeat true=on, false=off."""
        params = {"plantId": plant_id, "colSn": col_sn, "heartBeat": heartbeat}
        return self._data(self._request("GET", "/col/switch", params=params))

    # ------------------------------------------------- device relationships

    def plant_string_devices(self, plant_id: int) -> List[Dict[str, Any]]:
        """GET /device/plantGroupStringTree - strings and their devices.

        NOTE: the published docs list this endpoint with a ``localhost:8044``
        URL and no ``/api`` prefix. This client assumes it follows the same
        ``/api/openapi/...`` convention as the others; verify against a real
        account.
        """
        return self._data(
            self._request("GET", "/device/plantGroupStringTree", params={"plantId": plant_id})
        )

    def update_archives(
        self,
        plant_id: int,
        collector_sn: str,
        devices: Sequence[Mapping[str, str]],
        inverter_number: str,
        group_number: str,
        branch_num: int,
        branch_order: int,
    ) -> bool:
        """POST /col/updateArchives - deploy & sync archive.

        ``devices`` is a list of ``{"sn": device_sn, "gp": "1.1"}``.
        ``branch_num``: 1=single, 2=dual. ``branch_order``: 0=PV1->PV2, 1=PV2->PV1.
        """
        body = {
            "plantId": plant_id,
            "sn": collector_sn,
            "list": [dict(d) for d in devices],
            "inverterNumber": str(inverter_number),
            "groupNumber": str(group_number),
            "branchNum": branch_num,
            "branchOrder": branch_order,
        }
        return self._data(self._request("POST", "/col/updateArchives", body=body))

    def update_string_archive(
        self,
        plant_id: int,
        original_inverter_number: str,
        original_group_number: str,
        inverter_number: str,
        group_number: str,
        branch_num: int,
        branch_order: int,
    ) -> bool:
        """POST /col/updateStringArchive"""
        body = {
            "plantId": plant_id,
            "originalInverterNumber": str(original_inverter_number),
            "originalGroupNumber": str(original_group_number),
            "inverterNumber": str(inverter_number),
            "groupNumber": str(group_number),
            "branchNum": branch_num,
            "branchOrder": branch_order,
        }
        return self._data(self._request("POST", "/col/updateStringArchive", body=body))

    # ------------------------------------------------------------ networking

    def start_networking(self, col_sn: str, device_sns: Sequence[str]) -> bool:
        """POST /col/startNetwork"""
        body = {"colSn": col_sn, "deviceSnList": list(device_sns)}
        return self._data(self._request("POST", "/col/startNetwork", body=body))

    def networking_progress(self, col_sn: str) -> Dict[str, Any]:
        """GET /col/readPlcNetwork.

        ``status``: RUNNING / SUCCESS / FAILED / TIMEOUT; ``failSnList`` lists failures.
        """
        return self._data(self._request("GET", "/col/readPlcNetwork", params={"colSn": col_sn}))

    def wait_for_networking(
        self, col_sn: str, timeout: float = 300.0, interval: float = 5.0
    ) -> Dict[str, Any]:
        """Poll networking progress until it is no longer RUNNING."""
        deadline = time.monotonic() + timeout
        while True:
            progress = self.networking_progress(col_sn)
            if progress.get("status") != "RUNNING":
                return progress
            if time.monotonic() >= deadline:
                raise TimeoutError(f"networking for {col_sn} still RUNNING after {timeout}s")
            time.sleep(interval)

    # -------------------------------------------------------- control commands

    def plant_switch(self, plant_id: int, on: bool) -> str:
        """GET /plant/switchCmdRequest - async plant-wide switch. Returns task UUID."""
        return self._data(
            self._request(
                "GET", "/plant/switchCmdRequest", params={"plantId": plant_id, "status": on}
            )
        )

    def plant_switch_result(self, plant_id: int, task_uuid: str) -> Dict[str, str]:
        """GET /plant/switchCmdResCheck - ``{device_sn: "WAIT"|"TRUE"|"FALSE"}``."""
        return self._data(
            self._request(
                "GET",
                "/plant/switchCmdResCheck",
                params={"plantId": plant_id, "taskUUID": task_uuid},
            )
        )

    def wait_for_plant_switch(
        self, plant_id: int, task_uuid: str, timeout: float = 120.0, interval: float = 3.0
    ) -> Dict[str, str]:
        """Poll until no device is still WAIT."""
        deadline = time.monotonic() + timeout
        while True:
            result = self.plant_switch_result(plant_id, task_uuid)
            if not any(v == "WAIT" for v in result.values()):
                return result
            if time.monotonic() >= deadline:
                raise TimeoutError(f"plant switch task {task_uuid} still pending after {timeout}s")
            time.sleep(interval)

    def switch_device(self, device_sn: str, switch1: bool, switch2: Optional[bool] = None) -> bool:
        """POST /device/switchBySn (synchronous).

        Rapid-shutdown devices need both switch values; module optimizers only
        need ``switch1``.
        """
        body: Dict[str, Any] = {"deviceSn": device_sn, "switch1Val": switch1}
        if switch2 is not None:
            body["switch2Val"] = switch2
        return self._data(self._request("POST", "/device/switchBySn", body=body))

    # ------------------------------------------------------------- device data

    def latest_device_data(self, device_sn: str) -> Dict[str, Any]:
        """GET /device/latestData - ``deviceType`` plus ``branchOne``/``branchTwo``."""
        return self._data(
            self._request("GET", "/device/latestData", params={"deviceSn": device_sn})
        )

    def device_history_curve(
        self,
        device_sn: str,
        record_date: str,
        fields: Sequence[str],
        plant_id: Optional[int] = None,
    ) -> List[Dict[str, Any]]:
        """POST /device/historyCurve - one day of 15-minute points.

        ``record_date`` is ``YYYY-MM-DD``. Field names, e.g. module optimizer:
        total_generation, daily_generation, output_voltage, output_current,
        output_power, pcb_temperature, input_temperature, output_temperature;
        rapid shutdown: ``*_branch_one`` / ``*_branch_two`` variants.
        """
        body: Dict[str, Any] = {
            "deviceSn": device_sn,
            "recordDate": record_date,
            "fields": list(fields),
        }
        if plant_id is not None:
            body["plantId"] = plant_id
        return self._data(self._request("POST", "/device/historyCurve", body=body))

    # ------------------------------------------------------------------ alarms

    def query_plant_alarms(
        self,
        plant_id: int,
        *,
        device_type: str = "",
        fuzzy_sn: str = "",
        warn_type: str = "",
        warn_level: str = "",
        fix_type: str = "",
        start_day: str = "",
        end_day: str = "",
        page_num: int = 1,
        page_size: int = 30,
    ) -> Dict[str, Any]:
        """POST /warn/queryPlantWarnListByPage.

        Returns the whole payload (``{"total": int, "rows": [...], ...}``);
        this endpoint has no ``data`` wrapper.
        warn_level: "1" general, "2" critical. device_type: rapidShutdown /
        moduleOptimizer. Dates are ``YYYY-MM-DD``.
        """
        body = {
            "plantId": plant_id,
            "deviceType": device_type,
            "fuzzySn": fuzzy_sn,
            "warnType": warn_type,
            "warnLevel": warn_level,
            "fixType": fix_type,
            "startDay": start_day,
            "endDay": end_day,
            "pageNum": page_num,
            "pageSize": page_size,
        }
        return self._request("POST", "/warn/queryPlantWarnListByPage", body=body)

    def iter_plant_alarms(
        self, plant_id: int, page_size: int = 100, **filters: Any
    ) -> Iterator[Dict[str, Any]]:
        """Yield every alarm row, following pagination."""
        page = 1
        seen = 0
        while True:
            result = self.query_plant_alarms(
                plant_id, page_num=page, page_size=page_size, **filters
            )
            rows = result.get("rows") or []
            for row in rows:
                yield row
            seen += len(rows)
            if not rows or seen >= int(result.get("total") or 0):
                return
            page += 1
