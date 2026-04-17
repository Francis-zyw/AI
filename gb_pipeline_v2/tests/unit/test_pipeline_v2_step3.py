from __future__ import annotations

import unittest
from pathlib import Path

from pipeline_v2.step3_v2 import build_bill_item_key, match_bill_items_to_component, normalize_bill_items


PROJECT_ROOT = Path(__file__).resolve().parents[2]
COMPONENTS_PATH = PROJECT_ROOT / "tests" / "fixtures" / "step3" / "sample_components.json"
SYNONYM_LIBRARY_PATH = PROJECT_ROOT / "tests" / "fixtures" / "step3" / "sample_synonym_library.json"


class PipelineV2Step3Tests(unittest.TestCase):
    def test_build_bill_item_key_includes_ordinal(self) -> None:
        item = {
            "project_code": "010502010",
            "project_name": "钢筋混凝土墙",
            "project_features": "1. 混凝土种类\n2. 混凝土强度等级",
            "measurement_unit": "m3",
        }
        key1 = build_bill_item_key(item, 1)
        key2 = build_bill_item_key(item, 2)
        self.assertNotEqual(key1, key2)

    def test_normalize_bill_items_keeps_duplicate_project_codes(self) -> None:
        items = [
            {"project_code": "010502010", "project_name": "钢筋混凝土墙", "measurement_unit": "m3"},
            {"project_code": "010502010", "project_name": "钢筋混凝土墙", "measurement_unit": "m3"},
        ]
        normalized = normalize_bill_items(items)
        self.assertEqual(len(normalized), 2)
        self.assertNotEqual(normalized[0]["row_id"], normalized[1]["row_id"])

    def test_match_bill_items_to_component_uses_specified_component(self) -> None:
        payload = match_bill_items_to_component(
            bill_items=[
                {
                    "project_code": "010502010",
                    "project_name": "钢筋混凝土墙",
                    "project_features": "1. 混凝土种类\n2. 混凝土强度等级\n3. 墙厚>200mm",
                    "measurement_unit": "m3",
                    "quantity_rule": "按设计图示尺寸以体积计算",
                }
            ],
            component_type="砼墙",
            components_path=COMPONENTS_PATH,
            synonym_library_path=SYNONYM_LIBRARY_PATH,
        )

        row = payload["rows"][0]
        self.assertEqual(row["match_status"], "matched")
        self.assertEqual(row["resolved_component_name"], "砼墙")
        self.assertIn("1. 混凝土种类:TLX", row["feature_expression_text"])
        self.assertIn("2. 混凝土强度等级:TBH", row["feature_expression_text"])
        self.assertEqual(row["calculation_item_code"], "TJ")


if __name__ == "__main__":
    unittest.main()
