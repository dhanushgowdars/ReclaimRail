"""Run one bounded discovery plus Interactions API Phase 17B Gemini preflight."""

import argparse
import asyncio
import json
import sys
from datetime import UTC, datetime
from pathlib import Path

API_ROOT = Path(__file__).resolve().parents[1]
if str(API_ROOT) not in sys.path:
    sys.path.insert(0, str(API_ROOT))


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Make one owner-approved model-discovery request followed by one synthetic "
            "Gemini Interactions API preflight request."
        ),
    )
    parser.add_argument("--model", required=True)
    parser.add_argument("--thinking-level", required=True)
    parser.add_argument("--request-budget", required=True, type=int)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--acknowledge-live-gemini", required=True)
    return parser.parse_args()


async def run(args: argparse.Namespace) -> int:
    from app.core.config import get_settings
    from app.evaluation.phase17b_preflight import (
        PREFLIGHT_MAX_OUTPUT_TOKENS,
        PREFLIGHT_REQUEST_BUDGET,
        PREFLIGHT_REQUEST_TIMEOUT_SECONDS,
        PREFLIGHT_TOOL_NAME,
        run_phase17b_preflight,
        sanitized_preflight_report_json,
        validate_preflight_authorization,
    )
    from app.integrations.gemini.evidence_investigator import (
        GoogleGenAIEvidenceInvestigator,
    )

    candidate = validate_preflight_authorization(
        acknowledgement=args.acknowledge_live_gemini,
        request_budget=args.request_budget,
        model=args.model,
        thinking_level=args.thinking_level,
    )
    if args.output.suffix.lower() != ".json":
        raise ValueError("Phase 17B preflight evidence path must end in .json")
    if args.output.exists():
        raise FileExistsError("Phase 17B preflight evidence path already exists")

    settings = get_settings()
    if settings.gemini_api_key is None or not settings.gemini_api_key.get_secret_value().strip():
        raise ValueError("Gemini API access is not configured")
    provider = GoogleGenAIEvidenceInvestigator(
        api_key=settings.gemini_api_key.get_secret_value(),
        model_name=candidate.model,
        thinking_level=candidate.thinking_level,
        max_output_tokens=PREFLIGHT_MAX_OUTPUT_TOKENS,
        request_timeout_seconds=PREFLIGHT_REQUEST_TIMEOUT_SECONDS,
        forced_tool_name=PREFLIGHT_TOOL_NAME,
    )
    report = await run_phase17b_preflight(provider, candidate)
    sanitized = json.loads(sanitized_preflight_report_json(report))
    sanitized["run"] = {
        "generated_at": datetime.now(UTC).isoformat(),
        "owner_acknowledged": True,
        "provider": "gemini",
        "request_budget": PREFLIGHT_REQUEST_BUDGET,
        "request_timeout_seconds": PREFLIGHT_REQUEST_TIMEOUT_SECONDS,
        "max_output_tokens": PREFLIGHT_MAX_OUTPUT_TOKENS,
        "sdk_attempts_per_request": 1,
        "api_route": "generate_content",
        "seed": 0,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(sanitized, indent=2, sort_keys=True), encoding="utf-8")
    print(f"PreflightStatus={report.status}")
    print(f"EvidencePath={args.output}")
    return 0 if report.status == "passed" else 2


def main() -> None:
    raise SystemExit(asyncio.run(run(parse_args())))


if __name__ == "__main__":
    main()
