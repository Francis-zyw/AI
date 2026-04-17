from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from pipeline_v2.review_queue import build_step3_review_queue, load_review_ledger, write_review_ledger


class PipelineV2ReviewQueueTests(unittest.TestCase):
    def test_build_step3_review_queue_filters_pending_rows(self) -> None:
        rows = [
            {'row_id': '1', 'match_status': 'matched', 'review_status': 'reviewed'},
            {'row_id': '2', 'match_status': 'candidate_only', 'review_status': 'pending'},
            {'row_id': '3', 'match_status': 'unmatched', 'review_status': ''},
        ]
        queue = build_step3_review_queue(rows)
        self.assertEqual(len(queue), 2)
        self.assertEqual(queue[0]['row_id'], '2')
        self.assertEqual(queue[1]['row_id'], '3')

    def test_write_and_load_review_ledger(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            output = Path(temp_dir) / 'ledger.json'
            rows = [{'record_id': 'step3-1', 'row_id': '1', 'review_status': 'pending'}]
            write_review_ledger(str(output), rows, source_stage='step3')
            payload = load_review_ledger(str(output))
            self.assertEqual(payload['queued_rows'], 1)
            self.assertEqual(payload['rows'][0]['record_id'], 'step3-1')


if __name__ == '__main__':
    unittest.main()
