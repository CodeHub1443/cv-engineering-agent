"""
cv_agent.llm.credentials — project-scoped credential lookup for the LLM gateway.

Responsibility: find the gateway's API credentials from the process environment and then
the project ``.env`` file, without ever exporting, logging or printing a value (ADR-0021).

Rules (ADR-0021 §3):
  * Only names matching ``^CV_AGENT_[A-Z0-9_]+$`` are ever looked up or kept.
  * The generic Anthropic variable is never read as a credential, and there is no fallback
    to it. Its presence is noted (never its value) so a wrong-variable mistake is diagnosable.
  * ``.env`` values live in a module-private mapping. ``os.environ`` is never written.
  * Only the CLI entry point calls ``load_project_env_file()``, once, before dispatch.
  * POSIX: the file must be owned by the current user with no group/other bits.
    Windows: the ACL check is skipped (accepted gap, ADR-0021 §3.7).
"""

from __future__ import annotations

import os
import re
import sys
from pathlib import Path
from typing import Optional

from cv_agent.llm.errors import LLMCredentialError

_NAME_RE = re.compile(r"^CV_AGENT_[A-Z0-9_]+$")
_KEY_SHAPE_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")

# Module-private state. Never exposed, never copied into os.environ.
_LOADED: dict[str, str] = {}
_ENV_FILE: Optional[Path] = None
_NOT_SEARCHED_REASON: Optional[str] = None


def _parse(path: Path, text: str) -> dict[str, str]:
    values: dict[str, str] = {}
    for lineno, raw in enumerate(text.splitlines(), start=1):
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("export ") or line.startswith("export\t"):
            line = line[len("export") :].lstrip()
        key, sep, value = line.partition("=")
        key = key.strip()
        value = value.strip()
        if not sep or not _KEY_SHAPE_RE.match(key):
            raise _malformed(path, lineno)
        if value[:1] in ("'", '"'):
            if len(value) < 2 or value[-1] != value[0]:
                raise _malformed(path, lineno)
            value = value[1:-1]
        if _NAME_RE.match(key):
            values[key] = value
    return values


def _malformed(path: Path, lineno: int) -> LLMCredentialError:
    # Path and line number only: the line text may be a secret.
    return LLMCredentialError(f"malformed line in {path}:{lineno} (line content not shown)")


def load_project_env_file(path: Path) -> None:
    """Parse ``path`` into the module-private mapping. CLI ``main()`` only; never writes os.environ."""
    global _ENV_FILE, _NOT_SEARCHED_REASON
    if sys.platform != "win32":
        try:
            st = path.stat()
        except OSError as exc:
            raise LLMCredentialError(f"cannot read {path}: {type(exc).__name__}") from None
        if st.st_uid != os.getuid() or st.st_mode & 0o077:
            raise LLMCredentialError(
                f"{path} must be owned by the current user with no group/other permissions; "
                f"run: chmod 600 {path}"
            )
    try:
        text = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as exc:
        raise LLMCredentialError(f"cannot read {path}: {type(exc).__name__}") from None
    values = _parse(path, text)
    _LOADED.clear()
    _LOADED.update(values)
    _ENV_FILE = path
    _NOT_SEARCHED_REASON = None


def note_env_file_not_searched(reason: str) -> None:
    """Record why the project ``.env`` was not searched, for missing-key error messages."""
    global _ENV_FILE, _NOT_SEARCHED_REASON
    _LOADED.clear()
    _ENV_FILE = None
    _NOT_SEARCHED_REASON = reason


def searched_locations() -> tuple[str, ...]:
    """Human-readable places a credential was looked for. Never contains values."""
    if _ENV_FILE is not None:
        return ("process environment", f".env file: {_ENV_FILE}")
    reason = _NOT_SEARCHED_REASON or "not loaded"
    return ("process environment", f".env not searched: {reason}")


def get_credential(name: str) -> str:
    """Return the credential ``name`` (process environment first, then ``.env``).

    Raises LLMCredentialError for a name outside ``^CV_AGENT_[A-Z0-9_]+$`` or when no
    non-empty value is found. The error names the variable and searched locations only.
    """
    if not _NAME_RE.match(name):
        raise LLMCredentialError(
            "credential names must match ^CV_AGENT_[A-Z0-9_]+$ (ADR-0021); "
            f"got {name!r}"
        )
    value = os.environ.get(name) or _LOADED.get(name)
    if value:
        return value
    message = f"credential {name} not found. Searched: {'; '.join(searched_locations())}."
    if os.environ.get("ANTHROPIC_API_KEY"):
        message += " ANTHROPIC_API_KEY is set but ignored by design (ADR-0021)."
    raise LLMCredentialError(message)


def _reset_for_tests() -> None:
    """Clear all module state. Tests only."""
    global _ENV_FILE, _NOT_SEARCHED_REASON
    _LOADED.clear()
    _ENV_FILE = None
    _NOT_SEARCHED_REASON = None
