"""Executable negative typing contract for canonical immutable JSON scalars."""

from __future__ import annotations

import re
import subprocess
from pathlib import Path

import pytest

_REPOSITORY_ROOT = Path(__file__).resolve().parents[5]
_FIXTURE = Path("tests/unit_tests/core/human_input_v2/type_contracts/im_provider_immutable_json_rejections.py")
_EXPECTED_ERROR_LINES = {
    line_number
    for line_number, line in enumerate((_REPOSITORY_ROOT / "api" / _FIXTURE).read_text().splitlines(), start=1)
    if "# static-error" in line
}


@pytest.mark.parametrize(
    ("checker", "command", "diagnostic_pattern"),
    [
        pytest.param(
            "mypy",
            (
                "uv",
                "--directory",
                "api",
                "run",
                "mypy",
                "--no-error-summary",
                str(_FIXTURE),
            ),
            rf"{re.escape(str(_FIXTURE))}:(\d+): error:",
            id="mypy",
        ),
        pytest.param(
            "pyrefly",
            (
                "uv",
                "run",
                "--directory",
                "api",
                "--dev",
                "pyrefly",
                "check",
                "--summary=none",
                "--use-ignore-files=false",
                "--disable-project-excludes-heuristics=true",
                "--project-excludes=.venv",
                "--project-excludes=migrations/",
                "--output-format=min-text",
                str(_FIXTURE),
            ),
            rf"ERROR {re.escape(str(_FIXTURE))}:(\d+):\d+",
            id="pyrefly",
        ),
    ],
)
def test_public_immutable_json_types_reject_raw_numeric_scalars(
    checker: str,
    command: tuple[str, ...],
    diagnostic_pattern: str,
) -> None:
    completed = subprocess.run(
        command,
        cwd=_REPOSITORY_ROOT,
        check=False,
        capture_output=True,
        text=True,
    )
    output = completed.stdout + completed.stderr

    assert completed.returncode != 0, f"{checker} accepted raw bool, int, and float immutable JSON scalars"
    diagnostic_lines = {int(line) for line in re.findall(diagnostic_pattern, output, flags=re.MULTILINE)}
    assert diagnostic_lines == _EXPECTED_ERROR_LINES, output
