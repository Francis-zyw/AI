from __future__ import annotations

import unittest

from pipeline_v2.step1_chapter_ocr.core import _ExtractorRun
from pipeline_v2.step1_chapter_ocr.models import RegionResult


def make_region(
    *,
    index: int,
    outline_index: int,
    level: int,
    title: str,
    path: list[str],
    path_text: str,
    parent_index: int | None = None,
    parent_title: str | None = None,
    table_count: int = 0,
    table_row_count: int = 0,
) -> RegionResult:
    return RegionResult(
        index=index,
        outline_index=outline_index,
        level=level,
        title=title,
        path=path,
        path_text=path_text,
        parent_index=parent_index,
        parent_title=parent_title,
        pdf_page_start=1,
        pdf_page_end=1,
        body_page_start=1,
        body_page_end=1,
        text_source="unit_test",
        start_anchor_found=True,
        end_anchor_found=True,
        text_length=0,
        output_file=None,
        table_count=table_count,
        table_row_count=table_row_count,
        non_table_text="",
        text="",
    )


class Step1ChapterExportTests(unittest.TestCase):
    def test_build_chapter_packages_skips_non_bill_chapters_and_keeps_indices_dense(self) -> None:
        extractor = _ExtractorRun.__new__(_ExtractorRun)
        flat_regions = [
            make_region(
                index=1,
                outline_index=1,
                level=1,
                title="1 总则",
                path=["1 总则"],
                path_text="1 总则",
            ),
            make_region(
                index=2,
                outline_index=2,
                level=1,
                title="附录A 土石方工程",
                path=["附录A 土石方工程"],
                path_text="附录A 土石方工程",
            ),
            make_region(
                index=3,
                outline_index=3,
                level=2,
                title="A.1 土方工程",
                path=["附录A 土石方工程", "A.1 土方工程"],
                path_text="附录A 土石方工程 > A.1 土方工程",
                parent_index=2,
                parent_title="附录A 土石方工程",
                table_count=1,
                table_row_count=3,
            ),
        ]

        packages = extractor.build_chapter_packages(flat_regions)

        self.assertEqual(len(packages), 1)
        chapter_meta = packages[0]["chapter"]
        self.assertEqual(chapter_meta["title"], "附录A 土石方工程")
        self.assertEqual(chapter_meta["chapter_index"], 1)
        self.assertEqual(chapter_meta["slug"], "001_附录A_土石方工程")
        self.assertEqual(chapter_meta["region_count"], 2)
        self.assertEqual(chapter_meta["regions_with_tables"], 1)


if __name__ == "__main__":
    unittest.main()
