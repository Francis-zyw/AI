from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from pipeline_v2.import_legacy import import_legacy_outputs


class PipelineV2ImportLegacyTests(unittest.TestCase):
    def test_import_legacy_outputs_creates_manifest_and_imports_files(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir) / 'proj'
            step1 = root / 'legacy' / 'step1'
            step2 = root / 'legacy' / 'step2'
            step3 = root / 'legacy' / 'step3'
            (step1 / 'chapter_regions').mkdir(parents=True, exist_ok=True)
            step2.mkdir(parents=True, exist_ok=True)
            step3.mkdir(parents=True, exist_ok=True)
            (step1 / 'chapter_index.json').write_text('{}', encoding='utf-8')
            (step1 / 'table_regions.json').write_text('{}', encoding='utf-8')
            (step1 / 'chapter_regions' / 'x.json').write_text('{}', encoding='utf-8')
            (step2 / 'component_matching_result.json').write_text('{}', encoding='utf-8')
            (step2 / 'synonym_library.json').write_text('{}', encoding='utf-8')
            (step2 / 'run_summary.json').write_text('{}', encoding='utf-8')
            (step3 / 'project_component_feature_calc_matching_result.json').write_text('{"rows": []}', encoding='utf-8')
            (step3 / 'local_rule_project_component_feature_calc_result.json').write_text('{"rows": []}', encoding='utf-8')
            (step3 / 'run_summary.json').write_text('{}', encoding='utf-8')

            result = import_legacy_outputs(str(root), 'run-001', str(step1), str(step2), str(step3))
            manifest_path = Path(result['manifest_path'])
            self.assertTrue(manifest_path.exists())
            manifest = json.loads(manifest_path.read_text(encoding='utf-8'))
            self.assertEqual(manifest['run_id'], 'run-001')
            self.assertTrue(len(manifest['entries']) >= 6)


if __name__ == '__main__':
    unittest.main()
