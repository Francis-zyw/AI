from __future__ import annotations

import argparse
import unittest

from pipeline_v2.cli import build_parser


class PipelineV2CliTests(unittest.TestCase):
    def test_build_parser_removes_step2_legacy_preprocess_entry(self) -> None:
        parser = build_parser()
        subparsers_action = next(
            action for action in parser._actions if isinstance(action, argparse._SubParsersAction)
        )

        self.assertNotIn("step2-legacy-preprocess", subparsers_action.choices)
        self.assertIn("step2-execute", subparsers_action.choices)

