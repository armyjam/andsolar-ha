"""Tests for the Home-Assistant-free helpers in custom_components/andsolar/parsing.py."""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "custom_components" / "andsolar"))

from parsing import (  # noqa: E402
    BRANCH_ONE,
    BRANCH_TWO,
    branch_value,
    branches_for,
    mos_state,
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


if __name__ == "__main__":
    unittest.main()
