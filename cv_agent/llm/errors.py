"""
cv_agent.llm.errors — exception types for the LLM gateway.

Responsibility: name the gateway's failure modes so callers can catch them without
importing a provider module. Only the credential failure exists so far (ADR-0021);
the remaining gateway errors arrive with ADR-0020 slice G1.
"""

from __future__ import annotations


class LLMError(RuntimeError):
    """Base class for every error raised by the LLM gateway."""


class LLMCredentialError(LLMError):
    """A credential is missing, unreadable or malformed. Never carries a secret value."""
