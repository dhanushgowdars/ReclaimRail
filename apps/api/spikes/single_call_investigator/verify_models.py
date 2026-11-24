"""Bounded owner-authorized plain verification for candidate Gemini models."""

from __future__ import annotations

import asyncio
import json
import os
import sys
from pathlib import Path

from google import genai
from google.genai import types as genai_types

API_ROOT = Path(__file__).resolve().parents[2]
if str(API_ROOT) not in sys.path:
    sys.path.insert(0, str(API_ROOT))

from app.evaluation.phase17b_gemini38_smoke import load_isolated_key  # noqa: E402
from spikes.single_call_investigator.spike import (  # noqa: E402
    _safe_exception_type,
    _sanitized_error_message,
    _status_code,
)

MODELS = (
    "gemini-3.6-flash",
    "gemini-3.7-flash",
    "gemini-3.1-flash-lite",
    "gemini-3.8-flash",
)
OUTPUT = Path(__file__).resolve().parent / "model-verification-v10-20261124.json"
ENV_FILE = API_ROOT / ".env"
REQUEST_TIMEOUT_SECONDS = 120.0
MAX_REQUESTS = 8


def _write_once(payload: dict[str, object]) -> None:
    temporary = OUTPUT.with_suffix(".json.tmp")
    if OUTPUT.exists() or temporary.exists():
        raise FileExistsError("Model verification output already exists")
    try:
        with temporary.open("x", encoding="utf-8") as handle:
            json.dump(payload, handle, indent=2, sort_keys=True)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, OUTPUT)
    finally:
        temporary.unlink(missing_ok=True)


async def _verify_one(
    *,
    api_key: str,
    model: str,
    requests_used: list[int],
    sleep: object = asyncio.sleep,
) -> dict[str, object]:
    attempts: list[dict[str, object]] = []
    for attempt_number in (1, 2):
        if requests_used[0] >= MAX_REQUESTS:
            raise RuntimeError("model_verification_request_budget_exhausted")
        requests_used[0] += 1
        client = genai.Client(
            api_key=api_key,
            http_options=genai_types.HttpOptions(
                api_version="v1beta",
                timeout=int(REQUEST_TIMEOUT_SECONDS * 1000),
                retry_options=genai_types.HttpRetryOptions(attempts=1),
            ),
        )
        async_client = client.aio
        try:
            async with asyncio.timeout(REQUEST_TIMEOUT_SECONDS):
                response = await async_client.models.generate_content(
                    model=model,
                    contents="Reply with exactly: working",
                    config=genai_types.GenerateContentConfig(
                        max_output_tokens=16,
                        seed=0,
                        automatic_function_calling=genai_types.AutomaticFunctionCallingConfig(
                            disable=True,
                        ),
                        automatic_continuation=False,
                    ),
                )
            exact = bool(response.text and response.text.strip().casefold() == "working")
            attempts.append(
                {
                    "attempt": attempt_number,
                    "http_status": 200,
                    "exception_type": None,
                    "sanitized_error_message": None,
                }
            )
            return {
                "model": model,
                "eligible": exact,
                "exact_match": exact,
                "served_model": str(response.model_version or model).removeprefix("models/"),
                "attempts": attempts,
            }
        except Exception as error:  # noqa: BLE001 - sanitized provider boundary
            status = _status_code(error)
            message = _sanitized_error_message(error, status)
            attempts.append(
                {
                    "attempt": attempt_number,
                    "http_status": status,
                    "exception_type": _safe_exception_type(error),
                    "sanitized_error_message": message,
                }
            )
            unavailable = status == 404 or "unavailable to new users" in message.casefold()
            if status == 503 and attempt_number == 1 and not unavailable:
                await sleep(60.0)  # type: ignore[operator]
                continue
            return {
                "model": model,
                "eligible": False,
                "exact_match": False,
                "served_model": None,
                "attempts": attempts,
            }
        finally:
            await async_client.aclose()
            client.close()
    raise AssertionError("Verification loop must return")


async def run() -> int:
    requests_used = [0]
    api_key = load_isolated_key(ENV_FILE)
    results = [
        await _verify_one(api_key=api_key, model=model, requests_used=requests_used)
        for model in MODELS
    ]
    payload: dict[str, object] = {
        "requests_used": requests_used[0],
        "results": results,
    }
    _write_once(payload)
    eligible = sum(bool(result["eligible"]) for result in results)
    print(f"requests={requests_used[0]} models={len(results)} eligible={eligible}")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(run()))
