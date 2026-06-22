"""Cross-ecosystem compatibility modules."""

from agentanycast.compat.a2a_v1 import (
    card_from_a2a_json,
    card_to_a2a_json,
    message_from_a2a_json,
    message_to_a2a_json,
    skill_from_a2a_json,
    skill_to_a2a_json,
    task_from_a2a_json,
    task_to_a2a_json,
)
from agentanycast.compat.oasf import (
    card_from_oasf_record,
    card_to_oasf_record,
    skill_from_oasf,
    skill_to_oasf,
)

__all__ = [
    "card_from_a2a_json",
    "card_to_a2a_json",
    "card_from_oasf_record",
    "card_to_oasf_record",
    "message_from_a2a_json",
    "message_to_a2a_json",
    "skill_from_a2a_json",
    "skill_to_a2a_json",
    "skill_from_oasf",
    "skill_to_oasf",
    "task_from_a2a_json",
    "task_to_a2a_json",
]
