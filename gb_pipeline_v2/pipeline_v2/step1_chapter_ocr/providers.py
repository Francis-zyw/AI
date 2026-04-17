from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import List, Optional, Sequence
import os
import shlex
import shutil
import subprocess
import sys

import fitz
import numpy as np


@dataclass
class PageTextResult:
    text: str
    source: str

    @property
    def normalized_length(self) -> int:
        return sum(1 for char in self.text if char.isalnum() or ("\u4e00" <= char <= "\u9fff"))


class BasePageTextProvider(ABC):
    name = "base"

    @abstractmethod
    def extract(self, doc: fitz.Document, page_index: int) -> Optional[PageTextResult]:
        raise NotImplementedError


class TextLayerProvider(BasePageTextProvider):
    name = "text_layer"

    def extract(self, doc: fitz.Document, page_index: int) -> Optional[PageTextResult]:
        text = doc[page_index].get_text("text").strip()
        if not text:
            return None
        return PageTextResult(text=text, source=self.name)


class PaddleOCRProvider(BasePageTextProvider):
    name = "paddleocr"

    def __init__(
        self,
        lang: str = "ch",
        use_angle_cls: bool = True,
        use_gpu: bool = False,
        dpi: int = 300,
        auto_install: bool = True,
        install_commands: Optional[Sequence[Sequence[str]]] = None,
    ):
        self.lang = lang
        self.use_angle_cls = use_angle_cls
        self.use_gpu = use_gpu
        self.dpi = dpi
        self.auto_install = auto_install
        self.install_commands = list(install_commands) if install_commands is not None else self._build_default_install_commands()
        self._engine = None
        self._install_attempted = False

    def _detect_python_command(self) -> List[str]:
        if sys.executable and os.path.exists(sys.executable):
            return [sys.executable]

        python3 = shutil.which("python3")
        if python3:
            return [python3]

        python = shutil.which("python")
        if python:
            return [python]

        if os.name == "nt":
            py_launcher = shutil.which("py")
            if py_launcher:
                return [py_launcher, "-3"]

        raise RuntimeError("No usable Python interpreter was found for PaddleOCR auto-install.")

    def _build_default_install_commands(self) -> List[List[str]]:
        python_cmd = self._detect_python_command()
        return [
            [*python_cmd, "-m", "pip", "install", "paddlepaddle"],
            [*python_cmd, "-m", "pip", "install", "paddleocr"],
        ]

    def _run_install_commands(self) -> None:
        custom_install = os.environ.get("STEP1_PADDLE_INSTALL_CMD", "").strip()
        commands = self.install_commands
        if custom_install:
            commands = [shlex.split(custom_install)]

        for command in commands:
            subprocess.run(command, check=True)

    def _get_engine(self):
        if self._engine is not None:
            return self._engine

        try:
            from paddleocr import PaddleOCR
        except ImportError as exc:
            if not self.auto_install:
                raise ImportError(
                    "PaddleOCR provider requested but paddleocr is not installed. "
                    "Enable auto-install or install it first."
                ) from exc
            if self._install_attempted:
                raise ImportError(
                    "PaddleOCR auto-install was attempted but paddleocr is still unavailable."
                ) from exc

            self._install_attempted = True
            print("[pipeline_v2.step1_chapter_ocr] PaddleOCR not found, installing dependencies...")
            try:
                self._run_install_commands()
                from paddleocr import PaddleOCR
            except Exception as install_exc:
                raise RuntimeError(
                    "Failed to auto-install PaddleOCR. "
                    "Set STEP1_PADDLE_INSTALL_CMD for a custom install command if needed."
                ) from install_exc

        self._engine = PaddleOCR(
            use_angle_cls=self.use_angle_cls,
            lang=self.lang,
            use_gpu=self.use_gpu,
            show_log=False,
        )
        return self._engine

    def extract(self, doc: fitz.Document, page_index: int) -> Optional[PageTextResult]:
        engine = self._get_engine()
        page = doc[page_index]
        zoom = self.dpi / 72
        pix = page.get_pixmap(matrix=fitz.Matrix(zoom, zoom))
        channels = 4 if pix.alpha else 3
        image = np.frombuffer(pix.samples, dtype=np.uint8).reshape(pix.height, pix.width, channels)
        if channels == 4:
            image = image[:, :, :3]

        result = engine.ocr(image, cls=True)
        if not result or not result[0]:
            return None

        lines: List[str] = []
        for item in result[0]:
            text = item[1][0].strip()
            if text:
                lines.append(text)

        if not lines:
            return None

        return PageTextResult(text="\n".join(lines), source=self.name)


class PageTextResolver:
    def __init__(self, providers: Sequence[BasePageTextProvider], minimum_normalized_length: int = 1):
        if not providers:
            raise ValueError("At least one page text provider is required.")
        self.providers = list(providers)
        self.minimum_normalized_length = minimum_normalized_length

    @property
    def provider_names(self) -> List[str]:
        return [provider.name for provider in self.providers]

    def resolve(self, doc: fitz.Document, page_index: int) -> PageTextResult:
        best_result: Optional[PageTextResult] = None
        for provider in self.providers:
            result = provider.extract(doc, page_index)
            if result is None:
                continue
            if result.normalized_length >= self.minimum_normalized_length:
                return result
            if best_result is None or result.normalized_length > best_result.normalized_length:
                best_result = result

        if best_result is not None:
            return best_result
        return PageTextResult(text="", source="empty")
