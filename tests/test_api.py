"""Offline tests: the client talks to a local mock server, never the real API."""

import json
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "custom_components" / "andsolar"))

from api import AndSolarClient, ApiError, AuthError, DEFAULT_BASE_URL  # noqa: E402

ALARMS = [{"id": i, "deviceSn": f"SN{i}"} for i in range(1, 6)]


class State:
    def __init__(self):
        self.login_count = 0
        self.valid_token = None
        self.requests = []  # (method, path, headers, body)


STATE = State()


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *args):  # silence
        pass

    def _reply(self, status, payload):
        raw = json.dumps(payload).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)

    def _handle(self):
        url = urlparse(self.path)
        query = {k: v[0] for k, v in parse_qs(url.query).items()}
        length = int(self.headers.get("Content-Length") or 0)
        body = json.loads(self.rfile.read(length)) if length else None
        STATE.requests.append((self.command, url.path, dict(self.headers), query, body))

        if self.headers.get("Version") != "openapi":
            return self._reply(400, {"code": 400, "msg": "missing Version header"})

        if url.path == "/api/openapi/login":
            if query.get("password") != "good":
                return self._reply(200, {"code": 500, "msg": "bad credentials", "data": None})
            STATE.login_count += 1
            STATE.valid_token = f"tok-{STATE.login_count}"
            return self._reply(200, {"code": 200, "data": {"token": STATE.valid_token}})

        if self.headers.get("Authorization") != f"Bearer {STATE.valid_token}":
            return self._reply(401, {"code": 401, "msg": "Unauthorized"})

        if url.path == "/api/openapi/plant/queryList":
            return self._reply(200, {"code": 200, "msg": None, "data": [{"id": 1}]})
        if url.path == "/api/openapi/module/getViewListNoData":
            return self._reply(
                200,
                {
                    "code": 200,
                    "msg": None,
                    "data": [{"id": 92310, "deviceSn": "AB2220324C0108A", "branch": 2}],
                },
            )
        if url.path == "/api/openapi/col/switch":
            return self._reply(200, {"code": 200, "data": True})
        if url.path == "/api/openapi/col/check":
            return self._reply(200, {"code": 200, "data": {"passed": False, "code": 4002}})
        if url.path == "/api/openapi/device/latestData":
            return self._reply(200, {"code": 500, "msg": "device not found", "data": None})
        if url.path == "/api/openapi/warn/queryPlantWarnListByPage":
            size, num = body["pageSize"], body["pageNum"]
            rows = ALARMS[(num - 1) * size : num * size]
            return self._reply(200, {"total": len(ALARMS), "rows": rows, "code": 200})
        return self._reply(404, {"code": 404})

    do_GET = do_POST = do_DELETE = _handle


class ClientTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        cls.base = f"http://127.0.0.1:{cls.server.server_address[1]}"
        threading.Thread(target=cls.server.serve_forever, daemon=True).start()

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()

    def setUp(self):
        STATE.login_count = 0
        STATE.valid_token = None
        STATE.requests.clear()
        self.client = AndSolarClient("demo", "good", base_url=self.base, timeout=5)

    def test_default_base_url_is_production(self):
        self.assertEqual(DEFAULT_BASE_URL, "https://ap.andsolartech.com")

    def test_login_then_authenticated_request_has_required_headers(self):
        self.assertEqual(self.client.list_plants(), [{"id": 1}])
        method, path, headers, query, _ = STATE.requests[-1]
        self.assertEqual(path, "/api/openapi/plant/queryList")
        self.assertEqual(headers["Authorization"], "Bearer tok-1")
        self.assertEqual(headers["Version"], "openapi")

    def test_token_is_cached(self):
        self.client.list_plants()
        self.client.list_plants()
        self.assertEqual(STATE.login_count, 1)

    def test_401_triggers_one_relogin_and_retry(self):
        self.client.list_plants()
        STATE.valid_token = "rotated-on-server"  # server invalidates our token
        self.assertEqual(self.client.list_plants(), [{"id": 1}])
        self.assertEqual(STATE.login_count, 2)

    def test_bad_credentials_raise_auth_error(self):
        bad = AndSolarClient("demo", "wrong", base_url=self.base, timeout=5)
        with self.assertRaises(AuthError):
            bad.list_plants()

    def test_non_200_code_raises_api_error(self):
        with self.assertRaises(ApiError) as ctx:
            self.client.latest_device_data("NOPE")
        self.assertEqual(ctx.exception.code, 500)

    def test_booleans_are_lowercase_in_query(self):
        self.client.set_collector_switch(1, "BC1", True)
        query = STATE.requests[-1][3]
        self.assertEqual(query["heartBeat"], "true")

    def test_check_collector_failure_is_data_not_exception(self):
        result = self.client.check_collector_sn("BC1")
        self.assertFalse(result["passed"])
        self.assertEqual(result["code"], 4002)

    def test_alarm_pagination_collects_all_rows(self):
        rows = list(self.client.iter_plant_alarms(10186, page_size=2))
        self.assertEqual([r["id"] for r in rows], [1, 2, 3, 4, 5])

    def test_get_plant_view_passes_plant_id(self):
        modules = self.client.get_plant_view(10494)
        self.assertEqual(modules[0]["id"], 92310)
        method, path, _, query, _ = STATE.requests[-1]
        self.assertEqual(method, "GET")
        self.assertEqual(path, "/api/openapi/module/getViewListNoData")
        self.assertEqual(query["plantId"], "10494")


if __name__ == "__main__":
    unittest.main()
