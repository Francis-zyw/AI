from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from pipeline_v2.step2_review_tool_bundle import build_step2_review_tool_bundle


class Step2ReviewToolBundleTests(unittest.TestCase):
    def _write_step2_fixture(self, root: Path) -> Path:
        step2_dir = root / "step2"
        step2_dir.mkdir(parents=True, exist_ok=True)
        for name in ("component_matching_result.json", "synonym_library.json", "run_summary.json"):
            (step2_dir / name).write_text(json.dumps({"name": name}, ensure_ascii=False), encoding="utf-8")
        return step2_dir

    def test_build_step2_review_tool_bundle_writes_windows_delivery_files(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            output_dir = Path(temp_dir) / "bundle"
            step2_dir = self._write_step2_fixture(Path(temp_dir))

            result = build_step2_review_tool_bundle(output_dir, step2_output_dir=step2_dir)

            html_path = Path(result["html_path"])
            bat_path = Path(result["bat_path"])
            readme_path = Path(result["readme_path"])
            copied_inputs = result["copied_inputs"]

            self.assertTrue(html_path.exists())
            self.assertTrue(bat_path.exists())
            self.assertTrue(readme_path.exists())
            self.assertEqual(len(copied_inputs), 3)
            self.assertIn("第二步结果人工修订工具", html_path.read_text(encoding="utf-8"))
            self.assertIn("start", bat_path.read_text(encoding="utf-8").lower())
            self.assertIn("不需要安装任何环境", readme_path.read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
