"""Non-live command startup coverage for the evaluation-only canary wrapper."""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

API_ROOT = Path(__file__).parents[1]
SCRIPT = API_ROOT / "scripts" / "run_phase17b_groq_canary.py"


def _non_live_environment() -> dict[str, str]:
    environment = os.environ.copy()
    environment.pop("PYTHONPATH", None)
    environment.pop("RECLAIMRAIL_GROQ_API_KEY", None)
    return environment


def _run(arguments: list[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, *arguments],
        cwd=API_ROOT,
        env=_non_live_environment(),
        capture_output=True,
        text=True,
        check=False,
        timeout=10,
    )


def test_direct_wrapper_help_requires_no_pythonpath_or_live_dependencies() -> None:
    result = _run([str(SCRIPT), "--help"])
    assert result.returncode == 0
    assert "--owner-approved-live-run" in result.stdout


def test_module_wrapper_help_is_supported_without_provider_construction() -> None:
    result = _run(["-m", "scripts.run_phase17b_groq_canary", "--help"])
    assert result.returncode == 0
    assert "--owner-approved-live-run" in result.stdout


def test_missing_live_acknowledgement_fails_before_creating_a_report(tmp_path: Path) -> None:
    destination = tmp_path / "would-be-report.json"
    result = _run([str(SCRIPT), "--output", str(destination)])
    assert result.returncode != 0
    assert "Refusing live provider invocation" in result.stderr
    assert not destination.exists()
