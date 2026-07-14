"""Agency skill governance public API.

The subsystem is disabled by default. Importing it never scans profiles, changes
configuration, or publishes shared skills.
"""

from .authority import AuthenticatedPrincipal, PrincipalAuthenticator, PromoterAuthority
from .hub import HubAcquisitionService
from .manager import SkillGovernanceManager
from .migration import apply_migration, plan_migration, restore_migration
from .models import ProposalState, ReviewRole, RiskClass
from .service import GovernancePaths, SkillGovernanceControlPlane, default_paths
from .store import GovernanceStore

__all__ = [
    "GovernancePaths",
    "GovernanceStore",
    "ProposalState",
    "ReviewRole",
    "RiskClass",
    "SkillGovernanceControlPlane",
    "SkillGovernanceManager",
    "AuthenticatedPrincipal",
    "PrincipalAuthenticator",
    "PromoterAuthority",
    "HubAcquisitionService",
    "apply_migration",
    "default_paths",
    "plan_migration",
    "restore_migration",
]
