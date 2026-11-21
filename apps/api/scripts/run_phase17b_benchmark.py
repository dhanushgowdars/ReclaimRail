"""Run the frozen Phase 17B corpus only after explicit owner approval."""

import argparse
import asyncio
import json
import sys
from datetime import UTC, datetime
from pathlib import Path

API_ROOT = Path(__file__).resolve().parents[1]
if str(API_ROOT) not in sys.path:
    sys.path.insert(0, str(API_ROOT))

LIVE_ACKNOWLEDGEMENT = "OWNER_APPROVED_PHASE17B_LIVE_GEMINI"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run one owner-approved Gemini pass over the frozen synthetic corpus.",
    )
    parser.add_argument("--model", required=True)
    parser.add_argument("--thinking-level", required=True)
    parser.add_argument("--corpus", type=Path, required=True)
    parser.add_argument("--checksum", type=Path, required=True)
    parser.add_argument("--request-budget", type=int, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--acknowledge-live-gemini", required=True)
    return parser.parse_args()


async def run(args: argparse.Namespace) -> None:
    from app.core.config import get_settings
    from app.evaluation.phase17b_benchmark import (
        load_frozen_corpus,
        run_frozen_corpus,
        sanitized_report_json,
    )
    from app.integrations.gemini.evidence_investigator import GoogleGenAIEvidenceInvestigator

    if args.acknowledge_live_gemini != LIVE_ACKNOWLEDGEMENT:
        raise ValueError("Live Gemini acknowledgement does not match the required owner token")
    settings = get_settings()
    if settings.gemini_api_key is None or not settings.gemini_api_key.get_secret_value().strip():
        raise ValueError("Gemini API access is not configured")
    corpus, digest = load_frozen_corpus(args.corpus, args.checksum)
    provider = GoogleGenAIEvidenceInvestigator(
        api_key=settings.gemini_api_key.get_secret_value(),
        model_name=args.model,
        thinking_level=args.thinking_level,
        max_output_tokens=settings.gemini_max_output_tokens,
        request_timeout_seconds=settings.gemini_request_timeout_seconds,
    )
    report = await run_frozen_corpus(
        provider,
        corpus,
        digest,
        request_budget=args.request_budget,
    )
    sanitized = json.loads(sanitized_report_json(report))
    sanitized["run"] = {
        "model": args.model,
        "thinking_level": args.thinking_level,
        "request_budget": args.request_budget,
        "generated_at": datetime.now(UTC).isoformat(),
        "provider": "gemini",
        "evidence_mode": "controlled_synthetic",
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(sanitized, indent=2, sort_keys=True), encoding="utf-8")


def main() -> None:
    asyncio.run(run(parse_args()))


if __name__ == "__main__":
    main()
