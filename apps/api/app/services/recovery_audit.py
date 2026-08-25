import hashlib
import json
import math
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import Enum, StrEnum
from uuid import UUID

AUDIT_SCHEMA_VERSION = "reclaimrail.recovery.audit.v1"
SUPPORTED_HASH_ALGORITHM = "sha256"


class RecoveryAuditVerificationReason(StrEnum):
    VALID = "valid"
    CASE_MISMATCH = "case_mismatch"
    SEQUENCE_GAP = "sequence_gap"
    PREVIOUS_HASH_MISMATCH = "previous_hash_mismatch"
    EVENT_HASH_MISMATCH = "event_hash_mismatch"
    UNSUPPORTED_HASH_ALGORITHM = "unsupported_hash_algorithm"


@dataclass(frozen=True, slots=True)
class RecoveryAuditChainEntry:
    recovery_case_id: UUID
    sequence_number: int
    event_type: str
    actor_type: str
    event_data: Mapping[str, object]
    previous_event_hash: str | None
    event_hash: str
    occurred_at: datetime
    agent_run_id: UUID | None = None
    recovery_action_id: UUID | None = None
    hash_algorithm: str = SUPPORTED_HASH_ALGORITHM

    def __post_init__(self) -> None:
        if self.sequence_number < 1:
            raise ValueError("Audit sequence number must be at least one")

        event_type = self.event_type.strip()
        actor_type = self.actor_type.strip().casefold()

        if not event_type:
            raise ValueError("Audit event type cannot be empty")

        if not actor_type:
            raise ValueError("Audit actor type cannot be empty")

        _require_timezone_aware(self.occurred_at)
        previous_event_hash = _normalize_optional_hash(self.previous_event_hash)
        event_hash = _normalize_required_hash(self.event_hash)

        object.__setattr__(self, "event_type", event_type)
        object.__setattr__(self, "actor_type", actor_type)
        object.__setattr__(self, "previous_event_hash", previous_event_hash)
        object.__setattr__(self, "event_hash", event_hash)
        object.__setattr__(self, "hash_algorithm", self.hash_algorithm.strip().casefold())


@dataclass(frozen=True, slots=True)
class RecoveryAuditVerification:
    valid: bool
    reason: RecoveryAuditVerificationReason
    checked_event_count: int
    broken_sequence_number: int | None = None


def _require_timezone_aware(value: datetime) -> None:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("Audit timestamp must be timezone-aware")


def _normalize_timestamp(value: datetime) -> str:
    _require_timezone_aware(value)
    return value.astimezone(UTC).isoformat(timespec="microseconds").replace("+00:00", "Z")


def _normalize_required_hash(value: str) -> str:
    normalized = value.strip().casefold()

    if len(normalized) != 64 or any(
        character not in "0123456789abcdef" for character in normalized
    ):
        raise ValueError("Audit hash must be a 64-character hexadecimal SHA-256 digest")

    return normalized


def _normalize_optional_hash(value: str | None) -> str | None:
    if value is None:
        return None

    return _normalize_required_hash(value)


def _canonicalize(value: object) -> object:
    if value is None or isinstance(value, (str, bool, int)):
        return value

    if isinstance(value, float):
        if not math.isfinite(value):
            raise ValueError("Audit event data cannot contain non-finite numbers")
        return value

    if isinstance(value, UUID):
        return str(value)

    if isinstance(value, datetime):
        return _normalize_timestamp(value)

    if isinstance(value, Enum):
        return _canonicalize(value.value)

    if isinstance(value, Mapping):
        canonical_mapping: dict[str, object] = {}

        for key, item in value.items():
            if not isinstance(key, str):
                raise TypeError("Audit event-data keys must be strings")
            canonical_mapping[key] = _canonicalize(item)

        return canonical_mapping

    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        return [_canonicalize(item) for item in value]

    raise TypeError(f"Unsupported audit event-data value: {type(value).__name__}")


def normalize_recovery_audit_event_data(
    event_data: Mapping[str, object],
) -> dict[str, object]:
    normalized: dict[str, object] = {}

    for key, value in event_data.items():
        if not isinstance(key, str):
            raise TypeError("Audit event-data keys must be strings")

        normalized[key] = _canonicalize(value)

    return normalized


def canonicalize_recovery_audit_material(
    *,
    recovery_case_id: UUID,
    sequence_number: int,
    event_type: str,
    actor_type: str,
    event_data: Mapping[str, object],
    previous_event_hash: str | None,
    occurred_at: datetime,
    agent_run_id: UUID | None = None,
    recovery_action_id: UUID | None = None,
) -> bytes:
    if sequence_number < 1:
        raise ValueError("Audit sequence number must be at least one")

    normalized_event_type = event_type.strip()
    normalized_actor_type = actor_type.strip().casefold()

    if not normalized_event_type:
        raise ValueError("Audit event type cannot be empty")

    if not normalized_actor_type:
        raise ValueError("Audit actor type cannot be empty")

    material = {
        "actor_type": normalized_actor_type,
        "agent_run_id": str(agent_run_id) if agent_run_id is not None else None,
        "event_data": normalize_recovery_audit_event_data(event_data),
        "event_type": normalized_event_type,
        "occurred_at": _normalize_timestamp(occurred_at),
        "previous_event_hash": _normalize_optional_hash(previous_event_hash),
        "recovery_action_id": (str(recovery_action_id) if recovery_action_id is not None else None),
        "recovery_case_id": str(recovery_case_id),
        "schema": AUDIT_SCHEMA_VERSION,
        "sequence_number": sequence_number,
    }

    serialized = json.dumps(
        material,
        ensure_ascii=False,
        allow_nan=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    return serialized.encode("utf-8")


def compute_recovery_audit_hash(
    *,
    recovery_case_id: UUID,
    sequence_number: int,
    event_type: str,
    actor_type: str,
    event_data: Mapping[str, object],
    previous_event_hash: str | None,
    occurred_at: datetime,
    agent_run_id: UUID | None = None,
    recovery_action_id: UUID | None = None,
) -> str:
    material = canonicalize_recovery_audit_material(
        recovery_case_id=recovery_case_id,
        sequence_number=sequence_number,
        event_type=event_type,
        actor_type=actor_type,
        event_data=event_data,
        previous_event_hash=previous_event_hash,
        occurred_at=occurred_at,
        agent_run_id=agent_run_id,
        recovery_action_id=recovery_action_id,
    )
    return hashlib.sha256(material).hexdigest()


def build_recovery_audit_entry(
    *,
    recovery_case_id: UUID,
    sequence_number: int,
    event_type: str,
    actor_type: str,
    event_data: Mapping[str, object],
    previous_event_hash: str | None,
    occurred_at: datetime,
    agent_run_id: UUID | None = None,
    recovery_action_id: UUID | None = None,
) -> RecoveryAuditChainEntry:
    event_hash = compute_recovery_audit_hash(
        recovery_case_id=recovery_case_id,
        sequence_number=sequence_number,
        event_type=event_type,
        actor_type=actor_type,
        event_data=event_data,
        previous_event_hash=previous_event_hash,
        occurred_at=occurred_at,
        agent_run_id=agent_run_id,
        recovery_action_id=recovery_action_id,
    )

    return RecoveryAuditChainEntry(
        recovery_case_id=recovery_case_id,
        sequence_number=sequence_number,
        event_type=event_type,
        actor_type=actor_type,
        event_data=event_data,
        previous_event_hash=previous_event_hash,
        event_hash=event_hash,
        occurred_at=occurred_at,
        agent_run_id=agent_run_id,
        recovery_action_id=recovery_action_id,
    )


def verify_recovery_audit_chain(
    entries: Sequence[RecoveryAuditChainEntry],
) -> RecoveryAuditVerification:
    if not entries:
        return RecoveryAuditVerification(
            valid=True,
            reason=RecoveryAuditVerificationReason.VALID,
            checked_event_count=0,
        )

    expected_case_id = entries[0].recovery_case_id
    expected_previous_hash: str | None = None

    for expected_sequence_number, entry in enumerate(entries, start=1):
        checked_before_failure = expected_sequence_number - 1

        if entry.recovery_case_id != expected_case_id:
            return RecoveryAuditVerification(
                valid=False,
                reason=RecoveryAuditVerificationReason.CASE_MISMATCH,
                checked_event_count=checked_before_failure,
                broken_sequence_number=entry.sequence_number,
            )

        if entry.sequence_number != expected_sequence_number:
            return RecoveryAuditVerification(
                valid=False,
                reason=RecoveryAuditVerificationReason.SEQUENCE_GAP,
                checked_event_count=checked_before_failure,
                broken_sequence_number=entry.sequence_number,
            )

        if entry.hash_algorithm != SUPPORTED_HASH_ALGORITHM:
            return RecoveryAuditVerification(
                valid=False,
                reason=RecoveryAuditVerificationReason.UNSUPPORTED_HASH_ALGORITHM,
                checked_event_count=checked_before_failure,
                broken_sequence_number=entry.sequence_number,
            )

        if entry.previous_event_hash != expected_previous_hash:
            return RecoveryAuditVerification(
                valid=False,
                reason=RecoveryAuditVerificationReason.PREVIOUS_HASH_MISMATCH,
                checked_event_count=checked_before_failure,
                broken_sequence_number=entry.sequence_number,
            )

        expected_hash = compute_recovery_audit_hash(
            recovery_case_id=entry.recovery_case_id,
            sequence_number=entry.sequence_number,
            event_type=entry.event_type,
            actor_type=entry.actor_type,
            event_data=entry.event_data,
            previous_event_hash=entry.previous_event_hash,
            occurred_at=entry.occurred_at,
            agent_run_id=entry.agent_run_id,
            recovery_action_id=entry.recovery_action_id,
        )

        if entry.event_hash != expected_hash:
            return RecoveryAuditVerification(
                valid=False,
                reason=RecoveryAuditVerificationReason.EVENT_HASH_MISMATCH,
                checked_event_count=checked_before_failure,
                broken_sequence_number=entry.sequence_number,
            )

        expected_previous_hash = entry.event_hash

    return RecoveryAuditVerification(
        valid=True,
        reason=RecoveryAuditVerificationReason.VALID,
        checked_event_count=len(entries),
    )
