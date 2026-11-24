"""Owner-gated controlled Hydrogen canary; never executes application tools."""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import logging
import os
import sys
from pathlib import Path

API_ROOT = Path(__file__).resolve().parents[1]
REPOSITORY_ROOT = API_ROOT.parents[1]
if str(API_ROOT) not in sys.path:
    sys.path.insert(0, str(API_ROOT))

from app.evaluation.phase17b_gemini38_smoke import load_isolated_key  # noqa: E402
from app.evaluation.phase17b_gemini_hydrogen_canary import (  # noqa: E402
    CANARY_MODELS,
    HYDROGEN_MODEL,
    SOURCE_RECEIPT_SHA256,
    HydrogenCanaryProvider,
    HydrogenCanaryReport,
    run_controlled_hydrogen_canary,
    sanitized_report_json,
)

RUNTIME_ROOT = REPOSITORY_ROOT / ".runtime" / "phase17b"
SOURCE_RECEIPT = RUNTIME_ROOT / "groq-controlled-synthetic-canary-20261121-final.json"
ENV_FILE = API_ROOT / ".env"
LEASE_PATH = RUNTIME_ROOT / ".gemini4-hydrogen-controlled-canary.lock"
LOGGER = logging.getLogger(__name__)


def verify_source_receipt() -> None:
    digest = hashlib.sha256(SOURCE_RECEIPT.read_bytes()).hexdigest()
    if digest != SOURCE_RECEIPT_SHA256:
        raise ValueError("Controlled canary source receipt SHA-256 mismatch")


def validate_destination(destination: Path) -> Path:
    target = destination.resolve()
    if target.parent != RUNTIME_ROOT.resolve() or target.suffix != ".json":
        raise ValueError("Canary output must be a JSON file under .runtime/phase17b")
    if target.exists():
        raise FileExistsError("Canary output already exists")
    return target


def write_report_once(destination: Path, report: HydrogenCanaryReport) -> None:
    target = validate_destination(destination)
    temporary = target.with_suffix(".json.tmp")
    if temporary.exists():
        raise FileExistsError("Canary temporary output already exists")
    try:
        with temporary.open("x", encoding="utf-8") as handle:
            handle.write(sanitized_report_json(report))
            handle.flush()
            os.fsync(handle.fileno())
        if target.exists():
            raise FileExistsError("Canary output already exists")
        os.replace(temporary, target)
    finally:
        temporary.unlink(missing_ok=True)


async def execute(destination: Path, model_name: str) -> HydrogenCanaryReport:
    verify_source_receipt()
    target = validate_destination(destination)
    RUNTIME_ROOT.mkdir(parents=True, exist_ok=True)
    with LEASE_PATH.open("x", encoding="utf-8") as lease:
        lease.write("active\n")
        lease.flush()
        os.fsync(lease.fileno())
    provider: HydrogenCanaryProvider | None = None
    try:
        target = validate_destination(target)
        provider = HydrogenCanaryProvider(
            api_key=load_isolated_key(ENV_FILE), model_name=model_name
        )
        report = await run_controlled_hydrogen_canary(provider)
        write_report_once(target, report)
        return report
    finally:
        if provider is not None:
            try:
                await provider.aclose()
            except Exception:  # noqa: BLE001 - report is already durable and sanitized
                LOGGER.warning("Canary client cleanup failed after report persistence")
        LEASE_PATH.unlink(missing_ok=True)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run one controlled Gemini 4 Hydrogen canary")
    parser.add_argument("destination", type=Path)
    parser.add_argument("--model", choices=sorted(CANARY_MODELS), default=HYDROGEN_MODEL)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    report = asyncio.run(execute(args.destination, args.model))
    print(
        f"status={report.final_status} starts={report.requests_started} "
        f"responses={report.responses_received}"
    )
    return 0 if report.final_status == "passed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
