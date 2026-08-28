import json
from pathlib import Path

from app.services.worker_supervision_service import EXPECTED_WORKERS

REPOSITORY_ROOT = Path(__file__).resolve().parents[3]
MANIFEST_PATH = REPOSITORY_ROOT / "ops" / "local-processes.json"


def test_local_process_manifest_covers_every_expected_worker_once() -> None:
    manifest = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
    worker_entries = [entry for entry in manifest["processes"] if entry["kind"] == "worker"]

    assert {entry["worker_name"] for entry in worker_entries} == {
        worker.value for worker in EXPECTED_WORKERS
    }
    assert len(worker_entries) == len(EXPECTED_WORKERS)


def test_local_process_manifest_has_unique_names_and_required_ports() -> None:
    manifest = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
    entries = manifest["processes"]

    assert len(entries) == 11
    assert len({entry["name"] for entry in entries}) == len(entries)
    assert {
        entry["name"]: entry.get("port") for entry in entries if entry["kind"] == "service"
    } == {
        "api": 8000,
        "webhook": 8001,
        "web": 3000,
    }
