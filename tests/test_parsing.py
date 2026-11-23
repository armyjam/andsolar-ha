"""Tests for the Home-Assistant-free helpers in custom_components/andsolar/parsing.py."""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "custom_components" / "andsolar"))

from parsing import (  # noqa: E402
    BRANCH_ONE,
    BRANCH_TWO,
    MODULE_OPTIMIZER,
    RAPID_SHUTDOWN,
    annotate_shared_panels,
    branch_key_for_index,
    branch_value,
    branches_for,
    effective_branch_key,
    extract_polygon_coords,
    layout_bounds,
    mos_state,
    panel_entity_unique_ids,
    panel_metrics,
    parse_plant_layout,
    parse_topology,
    to_float,
)

# Shape taken from the documented plantGroupStringTree response.
GROUPS = [
    {
        "groupStringId": 19103,
        "collectorSn": "BC2170725C0069A",
        "inverterNumber": "1",
        "groupNumber": "1",
        "deviceList": [
            {
                "deviceSn": "AE2100125C0022A",
                "deviceType": "rapidShutdown",
                "series": "AMCL Series-Gen2",
                "modelType": "AMCL-E2",
                "branchNum": 2,
            }
        ],
    },
    {
        "collectorSn": "BC2170725C0069A",
        "inverterNumber": "1",
        "groupNumber": "2",
        "deviceList": [
            {
                "deviceSn": "C90090824C0006A",
                "deviceType": "moduleOptimizer",
                "modelType": "AMCP-90",
                "branchNum": 1,
            },
            {"deviceType": "moduleOptimizer"},  # no serial number -> skipped
        ],
    },
]

# Shape taken from /api/openapi/module/getViewListNoData.
VIEW_MODULES = [
    {
        "id": 92310,
        "position": (
            '{"type":"Feature","state":{},"geometry":{"type":"Polygon","coordinates":[[['
            "120.51621917635202,31.236256391057438],[120.51622152328491,31.236236753937533],"
            "[120.51620962098241,31.236235750580917],[120.51620727404952,31.236255387701064],"
            '[120.51621917635202,31.236256391057438]]]},"properties":{},"id":1208460}'
        ),
        "deviceId": 9091,
        "deviceSn": "AB2220324C0108A",
        "collectorSn": "BB0210924C0049A",
        "branch": 2,
        "power": 550,
        "deviceType": "rapidShutdown",
        "data": None,
    },
    {
        "id": 92309,
        "position": (
            '{"type":"Feature","state":{"hover":false},"geometry":{"type":"Polygon","coordinates":[[['
            "120.51620710641146,31.236255387701064],[120.51620945334435,31.236235750580917],"
            "[120.51619738340378,31.236234747224316],[120.51619503647089,31.236254384344647],"
            '[120.51620710641146,31.236255387701064]]]},"properties":{},"id":1208459}'
        ),
        "deviceId": 9091,
        "deviceSn": "AB2220324C0108A",
        "collectorSn": "BB0210924C0049A",
        "branch": 1,
        "power": 550,
        "deviceType": "rapidShutdown",
        "data": None,
    },
    {"id": 92311, "deviceSn": "BADJSON", "position": "{not-json", "branch": 1},
    {"id": 92312, "position": None, "branch": 1},
]


class ParsingTests(unittest.TestCase):
    def test_to_float(self):
        self.assertEqual(to_float("4.43"), 4.43)
        self.assertEqual(to_float(686), 686.0)
        self.assertIsNone(to_float(None))
        self.assertIsNone(to_float(""))
        self.assertIsNone(to_float(True))
        self.assertIsNone(to_float("abc"))

    def test_parse_topology(self):
        devices = parse_topology(10487, GROUPS)
        self.assertEqual([d["sn"] for d in devices], ["AE2100125C0022A", "C90090824C0006A"])
        first = devices[0]
        self.assertEqual(first["plant_id"], 10487)
        self.assertEqual(first["type"], "rapidShutdown")
        self.assertEqual(first["branch_num"], 2)
        self.assertEqual(first["string"], "1")

    def test_parse_topology_handles_empty(self):
        self.assertEqual(parse_topology(1, None), [])
        self.assertEqual(parse_topology(1, [{"deviceList": None}]), [])

    def test_branches_for(self):
        self.assertEqual(branches_for("rapidShutdown", 2), [BRANCH_ONE, BRANCH_TWO])
        self.assertEqual(branches_for("rapidShutdown", 1), [BRANCH_ONE])
        self.assertEqual(branches_for("moduleOptimizer", 1), [BRANCH_ONE])
        self.assertEqual(branches_for(None, 2), [BRANCH_ONE])

    def test_branch_key_for_index(self):
        self.assertEqual(branch_key_for_index(1), (1, BRANCH_ONE))
        self.assertEqual(branch_key_for_index(2), (2, BRANCH_TWO))
        self.assertEqual(branch_key_for_index("2"), (2, BRANCH_TWO))
        self.assertEqual(branch_key_for_index(None), (1, BRANCH_ONE))

    def test_branch_value_and_mos(self):
        latest = {
            "deviceType": "rapidShutdown",
            "branchOne": {"mos": 1, "voltage": 13},
            "branchTwo": {"mos": 0},
        }
        self.assertEqual(branch_value(latest, BRANCH_ONE, "voltage"), 13)
        self.assertIsNone(branch_value(latest, BRANCH_TWO, "voltage"))
        self.assertIsNone(branch_value(None, BRANCH_ONE, "voltage"))
        self.assertTrue(mos_state(latest, BRANCH_ONE))
        self.assertFalse(mos_state(latest, BRANCH_TWO))
        self.assertIsNone(mos_state({"branchOne": {}}, BRANCH_ONE))

    def test_extract_polygon_coords(self):
        poly = {
            "type": "Polygon",
            "coordinates": [[[0, 0], [1, 0], [1, 1], [0, 1], [0, 0]]],
        }
        self.assertEqual(
            extract_polygon_coords(poly), [(0.0, 0.0), (1.0, 0.0), (1.0, 1.0), (0.0, 1.0)]
        )
        multi = {
            "type": "MultiPolygon",
            "coordinates": [[[[0, 0], [2, 0], [2, 2], [0, 0]]]],
        }
        self.assertEqual(extract_polygon_coords(multi), [(0.0, 0.0), (2.0, 0.0), (2.0, 2.0)])
        self.assertIsNone(extract_polygon_coords(None))
        self.assertIsNone(extract_polygon_coords("{invalid"))
        self.assertIsNone(extract_polygon_coords({"type": "Point", "coordinates": [1, 2]}))

    def test_parse_plant_layout(self):
        panels = parse_plant_layout(10494, VIEW_MODULES)
        self.assertEqual(len(panels), 2)
        self.assertEqual([p["id"] for p in panels], [92310, 92309])
        self.assertEqual(panels[0]["branch"], 2)
        self.assertEqual(panels[0]["branch_key"], BRANCH_TWO)
        self.assertEqual(panels[1]["branch"], 1)
        self.assertEqual(panels[1]["branch_key"], BRANCH_ONE)
        self.assertEqual(panels[0]["rated_power"], 550.0)
        # Closing vertex is stripped -> 4 corners
        self.assertEqual(len(panels[0]["points"]), 4)

        bounds = layout_bounds(panels)
        # Two adjacent ~1.14m x 2.19m panels side-by-side -> ~2.5m wide x ~2.4m tall
        self.assertGreater(bounds["width"], 2.0)
        self.assertLess(bounds["width"], 3.0)
        self.assertGreater(bounds["height"], 2.0)
        self.assertLess(bounds["height"], 2.8)

        # Normalized to origin (0, 0)
        all_x = [pt[0] for p in panels for pt in p["points"]]
        all_y = [pt[1] for p in panels for pt in p["points"]]
        self.assertEqual(min(all_x), 0.0)
        self.assertEqual(min(all_y), 0.0)

    def test_parse_plant_layout_handles_empty(self):
        self.assertEqual(parse_plant_layout(1, None), [])
        self.assertEqual(layout_bounds([]), {"width": 0.0, "height": 0.0})

    def test_panel_metrics_rapid_shutdown_and_optimizer(self):
        rs_latest = {
            "branchOne": {
                "dailyPowerGeneration": "1.24",
                "totalGeneration": "412.5",
                "totalOutputPower": 342,
                "voltage": "38.8",
                "current": "8.81",
                "temperature": 47.2,
                "mos": 1,
                "deviceStatus": "HEALTHY",
            },
            "branchTwo": {
                "totalOutputPower": 0,
                "mos": 0,
                "deviceStatus": "healthy",
            },
        }
        m1 = panel_metrics(rs_latest, RAPID_SHUTDOWN, BRANCH_ONE)
        self.assertEqual(m1["status"], "on")
        self.assertEqual(m1["values"]["daily_energy"], 1.24)
        self.assertEqual(m1["values"]["power"], 342.0)
        self.assertEqual(m1["values"]["voltage"], 38.8)

        m2 = panel_metrics(rs_latest, RAPID_SHUTDOWN, BRANCH_TWO)
        self.assertEqual(m2["status"], "off")
        self.assertFalse(m2["mos"])

        opt_latest = {
            "branchOne": {
                "dailyPowerGeneration": 2.05,
                "totalOutputPower": 455,
                "outputVoltage": 39.4,
                "outputCurrent": 11.55,
                "pcbTemperature": 50.1,
                "deviceStatus": "warning",
            }
        }
        mo = panel_metrics(opt_latest, MODULE_OPTIMIZER, BRANCH_ONE)
        self.assertEqual(mo["status"], "warning")
        self.assertEqual(mo["values"]["voltage"], 39.4)
        self.assertEqual(mo["values"]["temperature"], 50.1)

        offline = panel_metrics(None, RAPID_SHUTDOWN, BRANCH_ONE)
        self.assertEqual(offline["status"], "offline")

    def test_panel_entity_unique_ids(self):
        rs_ids = panel_entity_unique_ids("andsolar", "SN1", RAPID_SHUTDOWN, BRANCH_TWO)
        self.assertEqual(rs_ids["power"], ("sensor", "andsolar_SN1_branchTwo_totalOutputPower"))
        self.assertEqual(rs_ids["voltage"], ("sensor", "andsolar_SN1_branchTwo_voltage"))
        self.assertEqual(rs_ids["switch"], ("switch", "andsolar_SN1_branchTwo_switch"))

        opt_ids = panel_entity_unique_ids("andsolar", "SN2", MODULE_OPTIMIZER, BRANCH_ONE)
        self.assertEqual(opt_ids["voltage"], ("sensor", "andsolar_SN2_branchOne_outputVoltage"))
        self.assertEqual(
            opt_ids["temperature"], ("sensor", "andsolar_SN2_branchOne_outputTemperature")
        )

    def test_effective_branch_key_and_shared_optimizer_layout(self):
        # 1:2 module optimizer always reports on branchOne even if layout marks branch 2
        self.assertEqual(effective_branch_key(MODULE_OPTIMIZER, 1), (1, BRANCH_ONE))
        self.assertEqual(effective_branch_key(MODULE_OPTIMIZER, 2), (2, BRANCH_ONE))
        # Single-branch rapid shutdown collapses to branchOne; dual-branch keeps both
        self.assertEqual(effective_branch_key(RAPID_SHUTDOWN, 2, branch_num=1), (2, BRANCH_ONE))
        self.assertEqual(effective_branch_key(RAPID_SHUTDOWN, 2, branch_num=2), (2, BRANCH_TWO))

        # Dual-branch rapid shutdown panels have distinct sources -> shared_count = 1
        rs_panels = parse_plant_layout(10494, VIEW_MODULES)
        self.assertEqual([p["shared_count"] for p in rs_panels], [1, 1])

        # 1:2 module optimizer sharing one SN -> both get branchOne, shared_count = 2
        opt_modules = [
            {**VIEW_MODULES[0], "deviceType": MODULE_OPTIMIZER, "branch": 2},
            {**VIEW_MODULES[1], "deviceType": MODULE_OPTIMIZER, "branch": 1},
        ]
        opt_panels = parse_plant_layout(10494, opt_modules)
        self.assertEqual([p["branch_key"] for p in opt_panels], [BRANCH_ONE, BRANCH_ONE])
        self.assertEqual([p["shared_count"] for p in opt_panels], [2, 2])
        # Branch 1 (id 92309) gets shared_index 0 (primary), branch 2 (id 92310) gets 1
        by_id = {p["id"]: p for p in opt_panels}
        self.assertEqual(by_id[92309]["shared_index"], 0)
        self.assertEqual(by_id[92310]["shared_index"], 1)

        # annotate_shared_panels works deterministically by id when branches are identical
        same_branch = [
            {"id": 200, "sn": "OPT1", "branch": 1, "branch_key": BRANCH_ONE},
            {"id": 100, "sn": "OPT1", "branch": 1, "branch_key": BRANCH_ONE},
        ]
        annotate_shared_panels(same_branch)
        self.assertEqual(same_branch[1]["shared_index"], 0)
        self.assertEqual(same_branch[0]["shared_index"], 1)


if __name__ == "__main__":
    unittest.main()
