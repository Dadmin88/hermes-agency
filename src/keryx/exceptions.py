"""SDK exception types."""

from __future__ import annotations


class KeryxError(Exception):
    """Base error for the Keryx Python SDK."""


class DaemonConnectionError(KeryxError):
    """Failed to connect to the local keryx-daemon."""


class RegistryConnectionError(KeryxError):
    """Failed to connect to the relay skill registry."""


class PeerNotFoundError(KeryxError):
    """Requested peer is not known or not connected."""


class CardNotAvailableError(KeryxError):
    """No agent card is available for the requested peer."""


class SkillNotFoundError(KeryxError):
    """Discovery returned no agents for the requested skill."""