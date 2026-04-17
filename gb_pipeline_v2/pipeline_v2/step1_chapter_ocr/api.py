from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Optional

from .core import GBStandardChapterExtractor
from .providers import PaddleOCRProvider, PageTextResolver, TextLayerProvider


def create_extractor(
    use_paddleocr: bool = False,
    minimum_text_length: int = 1,
    auto_install_paddleocr: bool = True,
) -> GBStandardChapterExtractor:
    providers = [TextLayerProvider()]
    if use_paddleocr:
        providers.append(PaddleOCRProvider(auto_install=auto_install_paddleocr))
    resolver = PageTextResolver(providers=providers, minimum_normalized_length=minimum_text_length)
    return GBStandardChapterExtractor(text_resolver=resolver)


def process_pdf(
    pdf_path: str | Path,
    output_dir: str | Path | None = None,
    save_outputs: bool = True,
    use_paddleocr: bool = False,
    minimum_text_length: int = 1,
    auto_install_paddleocr: bool = True,
):
    extractor = create_extractor(
        use_paddleocr=use_paddleocr,
        minimum_text_length=minimum_text_length,
        auto_install_paddleocr=auto_install_paddleocr,
    )
    return extractor.process_pdf(
        pdf_path=pdf_path,
        output_dir=output_dir,
        save_outputs=save_outputs,
    )


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Extract GB outline regions from a PDF with arbitrary chapter depth.")
    parser.add_argument("--pdf", required=True, help="Path to the PDF file")
    parser.add_argument("--output", help="Output directory. Defaults to data/output/step1/<pdf-name>")
    parser.add_argument("--no-save", action="store_true", help="Return result without writing output files")
    parser.add_argument("--use-paddleocr", action="store_true", help="Enable PaddleOCR as fallback when available")
    parser.add_argument("--no-auto-install-paddleocr", action="store_true", help="Disable auto install for PaddleOCR")
    parser.add_argument("--minimum-text-length", type=int, default=1, help="Fallback threshold for provider switching")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    result = process_pdf(
        pdf_path=args.pdf,
        output_dir=args.output,
        save_outputs=not args.no_save,
        use_paddleocr=args.use_paddleocr,
        minimum_text_length=args.minimum_text_length,
        auto_install_paddleocr=not args.no_auto_install_paddleocr,
    )
    print(json.dumps(result.to_dict()["summary"], ensure_ascii=False, indent=2))
