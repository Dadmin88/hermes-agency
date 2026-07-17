"""Typed records and state constants for Agency skill governance."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from enum import StrEnum
from typing import Any


class ProposalState(StrEnum):
    INGESTED = "INGESTED"
    VALIDATING = "VALIDATING"
    VALIDATION_FAILED = "VALIDATION_FAILED"
    QUARANTINED = "QUARANTINED"
    AWAITING_ROUTINE_APPROVAL = "AWAITING_ROUTINE_APPROVAL"
    AWAITING_SECURITY_APPROVAL = "AWAITING_SECURITY_APPROVAL"
    AWAITING_CEO_APPROVAL = "AWAITING_CEO_APPROVAL"
    AUTHORIZED = "AUTHORIZED"
    REJECTED = "REJECTED"
    PROMOTING = "PROMOTING"
    PROMOTION_FAILED = "PROMOTION_FAILED"
    PROMOTED = "PROMOTED"
    SUPERSEDED = "SUPERSEDED"


TERMINAL_STATES = {
    ProposalState.VALIDATION_FAILED,
    ProposalState.QUARANTINED,
    ProposalState.REJECTED,
    ProposalState.PROMOTED,
    ProposalState.SUPERSEDED,
}


class RiskClass(StrEnum):
    ROUTINE = "routine"
    SECURITY = "security_sensitive"
    GOVERNANCE = "governance_sensitive"
    SECURITY_GOVERNANCE = "security_and_governance_sensitive"


class ReviewRole(StrEnum):
    ORCHESTRATOR = "orchestrator"
    SECURITY = "security"
    CEO = "ceo"


@dataclass(frozen=True)
class ValidationFinding:
    code: str
    severity: str
    path: str
    message: str

    def as_dict(self) -> dict[str, str]:
        return asdict(self)


@dataclass(frozen=True)
class ValidationResult:
    valid: bool
    quarantined: bool
    risk: RiskClass
    candidate_digest: str | None
    candidate_path: str | None
    findings: tuple[ValidationFinding, ...]

    def as_dict(self) -> dict[str, Any]:
        return {
            "valid": self.valid,
            "quarantined": self.quarantined,
            "risk": self.risk.value,
            "candidate_digest": self.candidate_digest,
            "candidate_path": self.candidate_path,
            "findings": [finding.as_dict() for finding in self.findings],
        }
