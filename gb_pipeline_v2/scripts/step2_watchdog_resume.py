#!/usr/bin/env python3
"""Retry a resumable Step2 pipeline command until it succeeds."""

from __future__ import annotations

import argparse
import os
import re
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import List


API_KEY_PATTERN = re.compile(r"sk-proj-[A-Za-z0-9_\-]+")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run pipeline_v2 step2-execute with automatic retry."
    )
    parser.add_argument("--project-root", type=Path, required=True)
    parser.add_argument("--python-bin", type=Path, required=True)
    parser.add_argument("--log-file", type=Path, required=True)
    parser.add_argument("--session-log", type=Path)
    parser.add_argument("--sleep-seconds", type=float, default=15.0)
    parser.add_argument("--max-attempts", type=int, default=0)
    parser.add_argument(
        "step2_args",
        nargs=argparse.REMAINDER,
        help="Arguments appended after `python -m pipeline_v2 step2-execute`.",
    )
    return parser.parse_args()


def extract_api_key(session_log: Path | None) -> str:
    existing = os.environ.get("OPENAI_API_KEY", "").strip()
    if existing:
        return existing
    if session_log is None:
        raise RuntimeError("OPENAI_API_KEY not set and --session-log not provided.")
    text = session_log.read_text(errors="ignore")
    matches = API_KEY_PATTERN.findall(text)
    if not matches:
        raise RuntimeError(f"No API key found in session log: {session_log}")
    return matches[-1]


def normalize_step2_args(step2_args: List[str]) -> List[str]:
    if step2_args and step2_args[0] == "--":
        return step2_args[1:]
    return step2_args


def log_line(log_file: Path, message: str) -> None:
    log_file.parent.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    with log_file.open("a", encoding="utf-8") as handle:
        handle.write(f"[{timestamp}] {message}\n")


def main() -> int:
    args = parse_args()
    api_key = extract_api_key(args.session_log)
    step2_args = normalize_step2_args(args.step2_args)
    if not step2_args:
        raise RuntimeError("Missing step2 arguments after `--`.")

    command = [
        str(args.python_bin),
        "-m",
        "pipeline_v2",
        "step2-execute",
        *step2_args,
    ]
    env = os.environ.copy()
    env["OPENAI_API_KEY"] = api_key
    env["PYTHONUNBUFFERED"] = "1"

    attempt = 0
    while True:
        attempt += 1
        log_line(args.log_file, f"step2 resume attempt={attempt}")
        with args.log_file.open("a", encoding="utf-8") as handle:
            process = subprocess.run(
                command,
                cwd=args.project_root,
                env=env,
                stdout=handle,
                stderr=subprocess.STDOUT,
            )
        log_line(args.log_file, f"step2 exit code={process.returncode}")
        if process.returncode == 0:
            return 0
        if args.max_attempts and attempt >= args.max_attempts:
            return process.returncode
        time.sleep(args.sleep_seconds)


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:  # pragma: no cover
        print(str(exc), file=sys.stderr)
        raise
