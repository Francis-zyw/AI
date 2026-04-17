from __future__ import annotations

import unittest

from pipeline_v2.step1_chapter_ocr.core import build_rows_from_column_lines, postprocess_table_rows


class TableRowParsingTests(unittest.TestCase):
    def test_keeps_merged_rule_inside_single_row(self) -> None:
        line_cells = [
            (["010101001", "挖单独土方", "土类别", "", "按原始地貌与预", ""], "010101001挖单独土方土类别按原始地貌与预"),
            (["", "", "", "", "设标高之间的挖填", ""], "设标高之间的挖填"),
            (["", "", "", "", "尺寸，以体积计算", ""], "尺寸，以体积计算"),
            (["", "", "", "m3", "", "1.开挖"], "m31.开挖"),
            (["010101002", "挖单独石方", "岩石类别", "", "", "1.运输"], "010101002挖单独石方岩石类别1.运输"),
        ]

        rows, leading_row = build_rows_from_column_lines(line_cells, continuation=False)
        rows = postprocess_table_rows(rows, "尺寸，以体积计算")

        self.assertIsNone(leading_row)
        self.assertEqual(len(rows), 2)
        self.assertEqual(rows[0].measurement_unit, "m3")
        self.assertEqual(rows[0].quantity_rule, "按原始地貌与预\n设标高之间的挖填\n尺寸，以体积计算")
        self.assertEqual(rows[1].measurement_unit, "m3")
        self.assertEqual(rows[1].quantity_rule, "按原始地貌与预\n设标高之间的挖填\n尺寸，以体积计算")

    def test_applies_continuation_prefix_to_first_row_on_new_page(self) -> None:
        next_page_rows, leading_row = build_rows_from_column_lines(
            [
                (["", "", "", "", "1.基础沟槽土方", ""], "1.基础沟槽土方"),
                (["", "", "", "", "按照设计图示基础", ""], "按照设计图示基础"),
                (["", "", "", "", "", "1.开挖、放坡（若有）、"], "1.开挖、放坡（若有）、"),
                (["010102002", "挖沟槽土方", "2.开挖深度", "", "", "3.场内运输"], "010102002挖沟槽土方2.开挖深度3.场内运输"),
            ],
            continuation=True,
        )

        self.assertIsNone(leading_row)
        self.assertEqual(next_page_rows[0].project_code, "010102002")
        self.assertIn("1.基础沟槽土方", next_page_rows[0].quantity_rule)
        self.assertIn("按照设计图示基础", next_page_rows[0].quantity_rule)
        self.assertIn("1.开挖、放坡", next_page_rows[0].work_content)

    def test_keeps_columnized_raw_line_cells(self) -> None:
        line_cells = [
            (["010101003", "", "", "", "", "2.回填"], "0101010032.回填"),
            (["", "石方回填", "2.密实度", "", "", ""], "石方回填2.密实度"),
        ]

        rows, _ = build_rows_from_column_lines(line_cells, continuation=False)

        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0].raw_line_cells[0]["项目编码"], "010101003")
        self.assertEqual(rows[0].raw_line_cells[0]["工作内容"], "2.回填")
        self.assertEqual(rows[0].raw_line_cells[1]["项目名称"], "石方回填")
        self.assertEqual(rows[0].raw_line_cells[1]["项目特征"], "2.密实度")

    def test_moves_split_work_sequence_to_next_row(self) -> None:
        rows, _ = build_rows_from_column_lines(
            [
                (["010101001", "挖单独土方", "土类别", "", "按原始地貌与预", "1.开挖"], "010101001挖单独土方土类别按原始地貌与预1.开挖"),
                (["", "", "", "", "设标高之间的挖填", "2.装车"], "设标高之间的挖填2.装车"),
                (["", "", "", "", "尺寸，以体积计算", "3.场内运输"], "尺寸，以体积计算3.场内运输"),
                (["010101002", "挖单独石方", "岩石类别", "", "", "1.运输"], "010101002挖单独石方岩石类别1.运输"),
                (["", "单独土", "1.材料品种", "", "", ""], "单独土1.材料品种"),
                (["010101003", "", "", "", "", "2.回填"], "0101010032.回填"),
                (["", "石方回填", "2.密实度", "", "", ""], "石方回填2.密实度"),
                (["", "", "", "", "", "3.压实"], "3.压实"),
            ],
            continuation=False,
        )

        processed = postprocess_table_rows(rows, "尺寸，以体积计算")

        self.assertEqual(processed[0].work_content, "1.开挖\n2.装车\n3.场内运输")
        self.assertEqual(processed[1].work_content, "1.开挖\n2.装车\n3.场内运输")
        self.assertEqual(processed[2].work_content, "1.运输\n2.回填\n3.压实")
        self.assertEqual(processed[1].quantity_rule, "按原始地貌与预\n设标高之间的挖填\n尺寸，以体积计算")
        self.assertEqual(processed[2].quantity_rule, "按原始地貌与预\n设标高之间的挖填\n尺寸，以体积计算")
        self.assertEqual(processed[1].measurement_unit, "m3")
        self.assertEqual(processed[2].measurement_unit, "m3")

    def test_moves_precode_rule_and_work_prefix_to_next_row(self) -> None:
        rows, _ = build_rows_from_column_lines(
            [
                (["010102004", "挖淤泥流砂", "开挖深度", "", "按设计图示位置、界限，以体积计算", ""], "010102004挖淤泥流砂开挖深度按设计图示位置、界限，以体积计算"),
                (["", "", "", "", "按设计图示基础", "1.开挖、放坡（若有）、"], "按设计图示基础1.开挖、放坡（若有）、"),
                (["", "", "", "", "（含垫层）底面积另", "挡土板围护（若有）"], "（含垫层）底面积另挡土板围护（若有）"),
                (["", "挖基坑石方", "", "", "", ""], "挖基坑石方"),
                (["010102005", "", "", "", "加工作面面积，乘", "2.装车"], "010102005加工作面面积，乘2.装车"),
                (["", "2.岩石类别", "", "", "以挖石深度，以体", "3.场内运输"], "2.岩石类别以挖石深度，以体3.场内运输"),
                (["", "", "", "", "积计算", "4.检底修边"], "积计算4.检底修边"),
            ],
            continuation=False,
        )

        self.assertEqual(rows[0].project_code, "010102004")
        self.assertEqual(rows[0].work_content, "")
        self.assertEqual(rows[1].project_code, "010102005")
        self.assertIn("按设计图示基础", rows[1].quantity_rule)
        self.assertIn("1.开挖、放坡", rows[1].work_content)
        self.assertIn("2.装车", rows[1].work_content)


if __name__ == "__main__":
    unittest.main()
