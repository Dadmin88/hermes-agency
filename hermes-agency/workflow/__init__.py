"""Pure deterministic workflow governance primitives.

This package deliberately has no imports from orchestration, Kanban, Keryx, or
runtime lifecycle modules. Later runtime PRs may adapt these stable primitives.
"""

from .errors import (
    ArtifactIdentityError,
    EventConflictError,
    GraphValidationError,
    IllegalTransitionError,
    ReviewerIndependenceError,
    SerializationError,
    VerdictConflictError,
    WorkflowError,
)
from .events import event, event_digest
from .graph import (
    active_controlling_gate,
    ready_gates,
    validate_artifact_identity,
    validate_reviewer_independence,
    validate_state,
    validate_workflow_graph,
)
from .models import (
    ArtifactIdentity,
    EventType,
    GateKind,
    GateStatus,
    OperatorDecision,
    OperatorDecisionStatus,
    ReviewVerdict,
    RevisionStatus,
    VerdictDecision,
    WorkflowEvent,
    WorkflowGate,
    WorkflowRevision,
    WorkflowRun,
    WorkflowState,
    WorkflowStatus,
)
from .serialization import restore_state, serialize_state
from .templates import ARCHITECTURE_GOVERNANCE, architecture_governance_state
from .transitions import start_successor_revision, transition

__all__ = [
    "ARCHITECTURE_GOVERNANCE",
    "ArtifactIdentity",
    "ArtifactIdentityError",
    "EventConflictError",
    "EventType",
    "GateKind",
    "GateStatus",
    "GraphValidationError",
    "IllegalTransitionError",
    "OperatorDecision",
    "OperatorDecisionStatus",
    "RevisionStatus",
    "ReviewVerdict",
    "ReviewerIndependenceError",
    "SerializationError",
    "VerdictConflictError",
    "VerdictDecision",
    "WorkflowError",
    "WorkflowEvent",
    "WorkflowGate",
    "WorkflowRevision",
    "WorkflowRun",
    "WorkflowState",
    "WorkflowStatus",
    "active_controlling_gate",
    "architecture_governance_state",
    "event",
    "event_digest",
    "ready_gates",
    "restore_state",
    "serialize_state",
    "start_successor_revision",
    "transition",
    "validate_artifact_identity",
    "validate_reviewer_independence",
    "validate_state",
    "validate_workflow_graph",
]
