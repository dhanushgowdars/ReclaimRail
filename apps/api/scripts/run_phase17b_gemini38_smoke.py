"""Run an owner-authorized bounded smoke for an explicitly allowlisted Gemini model."""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal, cast

API_ROOT = Path(__file__).resolve().parents[1]
if str(API_ROOT) not in sys.path:
    sys.path.insert(0, str(API_ROOT))

from app.evaluation.phase17b_gemini38_smoke import (  # noqa: E402
    GEMINI_38_KEY_NAME,
    GEMINI_38_MODEL,
    load_isolated_key,
    resolve_smoke_model,
    run_smoke_request,
    sanitized_receipt,
)


def _write_new(path: Path, payload: dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("x", encoding="utf-8") as handle:
        json.dump(payload, handle, indent=2, sort_keys=True)


async def run(
    output_dir: Path,
    *,
    model_name: str = GEMINI_38_MODEL,
    label: str | None = None,
) -> list[dict[str, object]]:
    if output_dir.name != "phase17b" or output_dir.parent.name != ".runtime":
        raise ValueError("Gemini 3.8 smoke output must be under .runtime/phase17b")
    key = load_isolated_key(API_ROOT / ".env")
    model = resolve_smoke_model(model_name)
    run_label = label or datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    results: list[dict[str, object]] = []
    kinds: tuple[Literal["model_metadata", "plain", "forced_function"], ...]
    if model.include_metadata_request:
        kinds = ("model_metadata", "plain", "forced_function")
    else:
        kinds = ("plain", "forced_function")
    for ordinal, raw_kind in enumerate(kinds, start=1):
        kind = cast(Literal["model_metadata", "plain", "forced_function"], raw_kind)
        receipt = await run_smoke_request(key, kind, model_name=model.model_name)
        payload = sanitized_receipt(receipt)
        model_slug = model.model_name.replace("gemini-", "gemini")
        path = output_dir / f"{model_slug}-smoke-{run_label}-{ordinal}-{kind}.json"
        _write_new(path, payload)
        results.append(payload)
        if kind == "model_metadata" and receipt.available is not True:
            break
        if kind == "plain" and receipt.outcome != "succeeded":
            break
    return results


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("output_dir", type=Path)
    parser.add_argument("--model", required=True)
    args = parser.parse_args()
    try:
        results = asyncio.run(run(args.output_dir, model_name=args.model))
    except Exception as error:
        if GEMINI_38_KEY_NAME in str(error):
            print(f"MissingVariable={GEMINI_38_KEY_NAME}")
        raise
    for result in results:
        print(
            "RequestKind={request_kind} Outcome={outcome} Status={http_status} "
            "LatencyMs={latency_ms}".format(**result)
        )


if __name__ == "__main__":
    main()
