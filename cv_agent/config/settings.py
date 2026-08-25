"""
cv_agent.config.settings — Configuration dataclasses and loader.

Config discovery order:
  1. Path explicitly passed to load_config()
  2. <repo_root>/config/default.toml
  3. Built-in defaults (no file needed — tests run without a config file)

Environment variable overrides are intentionally deferred to a later step.
"""

from __future__ import annotations

import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

if sys.version_info >= (3, 11):
    import tomllib  # stdlib from 3.11+
else:
    import tomli as tomllib  # type: ignore[no-redef]

# Repo root: cv_agent/config/settings.py → cv_agent/config/ → cv_agent/ → root
_REPO_ROOT = Path(__file__).parent.parent.parent


@dataclass
class LLMOverride:
    """Provider/model override for a specific named agent role."""

    provider: str
    model: str


@dataclass
class LLMConfig:
    """LLM provider configuration."""

    provider: str = "mock"
    model: str = "fake-1"
    # Keyed by agent role name (e.g. "planner", "critic")
    overrides: dict[str, LLMOverride] = field(default_factory=dict)


@dataclass
class AgentConfig:
    """Top-level agent configuration."""

    llm: LLMConfig = field(default_factory=LLMConfig)
    registry_path: Path = field(
        default_factory=lambda: _REPO_ROOT / "spec" / "capability_registry.json"
    )


def load_config(path: Optional[Path] = None) -> AgentConfig:
    """
    Load agent configuration from a TOML file.

    Args:
        path: Explicit path to a .toml config file.
              Defaults to <repo_root>/config/default.toml.
              If the file does not exist, built-in defaults are returned.

    Returns:
        Populated AgentConfig.
    """
    if path is None:
        path = _REPO_ROOT / "config" / "default.toml"

    if not path.exists():
        return AgentConfig()

    with open(path, "rb") as fh:
        raw = tomllib.load(fh)

    llm_raw: dict = raw.get("llm", {})
    overrides_raw: dict = llm_raw.get("overrides", {})

    overrides: dict[str, LLMOverride] = {
        role: LLMOverride(
            provider=role_cfg.get("provider", "mock"),
            model=role_cfg.get("model", "fake-1"),
        )
        for role, role_cfg in overrides_raw.items()
    }

    llm = LLMConfig(
        provider=llm_raw.get("provider", "mock"),
        model=llm_raw.get("model", "fake-1"),
        overrides=overrides,
    )

    registry_path_raw: Optional[str] = raw.get("registry_path")
    registry_path = (
        Path(registry_path_raw)
        if registry_path_raw
        else _REPO_ROOT / "spec" / "capability_registry.json"
    )

    return AgentConfig(llm=llm, registry_path=registry_path)
