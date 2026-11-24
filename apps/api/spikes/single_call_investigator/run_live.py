"""Owner-authorized live runner for the isolated single-call investigator spike."""

from __future__ import annotations

import asyncio
import os
import random
import sys
from pathlib import Path

API_ROOT = Path(__file__).resolve().parents[2]
if str(API_ROOT) not in sys.path:
    sys.path.insert(0, str(API_ROOT))

from app.evaluation.phase17b_benchmark import load_frozen_corpus  # noqa: E402
from app.evaluation.phase17b_gemini38_smoke import load_isolated_key  # noqa: E402
from spikes.single_call_investigator.spike import (  # noqa: E402
    GoogleStructuredTransport,
    RequestBudget,
    SingleCallGeminiProvider,
    run_scenarios,
    sanitized_report_json,
)

VERIFIED_MODEL_CHAIN: tuple[str, ...] = ()
MAX_REQUESTS = 40
SUBSET_IDS = tuple(f"p17b-{number:02d}" for number in range(1, 11))
SPIKE_DIR = Path(__file__).resolve().parent
OUTPUT = SPIKE_DIR / "live-report-v6-full-corpus-20261124.json"
CORPUS = API_ROOT / "benchmarks" / "phase17b" / "corpus-v2.json"
CHECKSUM = API_ROOT / "benchmarks" / "phase17b" / "corpus-v2.sha256"
ENV_FILE = API_ROOT / ".env"


def write_once(payload: str) -> None:
    temporary = OUTPUT.with_suffix(".json.tmp")
    if OUTPUT.exists() or temporary.exists():
        raise FileExistsError("Single-call spike output already exists")
    try:
        with temporary.open("x", encoding="utf-8") as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, OUTPUT)
    finally:
        temporary.unlink(missing_ok=True)


async def run() -> int:
    corpus, _ = load_frozen_corpus(CORPUS, CHECKSUM)
    scenarios_by_id = {scenario.scenario_id: scenario for scenario in corpus.scenarios}
    scenarios = tuple(scenarios_by_id[scenario_id] for scenario_id in SUBSET_IDS)
    provider = SingleCallGeminiProvider(
        transport=GoogleStructuredTransport(api_key=load_isolated_key(ENV_FILE)),
        models=VERIFIED_MODEL_CHAIN,
        budget=RequestBudget(MAX_REQUESTS),
    )
    report = await run_scenarios(
        provider,
        scenarios,
        scenario_gap_seconds=lambda: random.uniform(3.0, 5.0),
    )
    write_once(sanitized_report_json(report))
    print(
        f"requests={report.requests_used} scenarios={len(report.scenario_scores)} "
        f"thresholds_met={report.thresholds_met}"
    )
    return 0 if report.thresholds_met else 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(run()))
