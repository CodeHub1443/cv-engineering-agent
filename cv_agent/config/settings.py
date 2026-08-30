"""
cv_agent.config.settings — Configuration dataclasses and loader.

Config discovery order:
  1. Path explicitly passed to load_config()
  2. Packaged config/default.toml
  3. Built-in defaults (no file needed — tests run without a config file)

Environment variable overrides are intentionally deferred to a later step.
"""

from __future__ import annotations

import sys
from dataclasses import dataclass, field
from importlib.resources import files as resource_files
from importlib.resources.abc import Traversable
from pathlib import Path

if sys.version_info >= (3, 11):
    import tomllib
else:
    import tomli as tomllib  # type: ignore[no-redef]

_RESOURCE_PACKAGE = "cv_agent.resources"


def _resource_path(relative_path: str) -> Traversable:
    """Return a package resource without assuming it is a filesystem path."""
    return resource_files(_RESOURCE_PACKAGE).joinpath(relative_path)


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
    registry_path: Path | Traversable = field(
        default_factory=lambda: _resource_path("spec/capability_registry.json")
    )


def load_config(path: Path | Traversable | None = None) -> AgentConfig:
    """
    Load agent configuration from a TOML file.

    Args:
        path: Explicit path to a .toml config file.
              Defaults to packaged config/default.toml.
              If the file does not exist, built-in defaults are returned.

    Returns:
        Populated AgentConfig.
    """
    if path is None:
        path = _resource_path("config/default.toml")

    if not path.is_file():
        return AgentConfig()

    with path.open("rb") as fh:
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

    registry_path_raw: str | None = raw.get("registry_path")
    registry_path: Path | Traversable = (
        Path(registry_path_raw)
        if registry_path_raw
        else _resource_path("spec/capability_registry.json")
    )

    return AgentConfig(llm=llm, registry_path=registry_path)
