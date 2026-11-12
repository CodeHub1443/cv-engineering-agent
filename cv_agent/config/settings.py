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
from dataclasses import dataclass, field, fields
from importlib import resources
from importlib.resources import files as resource_files
from pathlib import Path
from typing import Any, Optional

try:
    # Real stdlib module, but typeshed gates it to Python 3.11+ (see
    # typeshed stdlib/VERSIONS); mypy targeting 3.10 correctly reports
    # import-not-found here — ignored below, not a bug.
    from importlib.resources.abc import Traversable  # type: ignore[import-untyped, import-not-found]  # Python 3.11+
except ImportError:  # pragma: no cover - exercised on Python < 3.12
    from importlib.abc import Traversable  # Python 3.10-3.11

if sys.version_info >= (3, 11):
    import tomllib  # stdlib from 3.11+
else:
    import tomli as tomllib  # type: ignore[no-redef]

from cv_agent.llm.clock import parse_utc_offset
from cv_agent.llm.errors import LLMConfigError
from cv_agent.llm.policy import DataClass, TaskClass

_RESOURCE_PACKAGE = "cv_agent.resources"
_REPO_ROOT = Path(__file__).resolve().parents[2]


def _resource_path(relative_path: str) -> Path:
    """Return the installed filesystem path for a packaged runtime resource."""
    resource = resources.files(_RESOURCE_PACKAGE).joinpath(relative_path)
    # A Traversable backed by a real filesystem package (the only kind this
    # repo produces) implements __fspath__ at runtime; the Traversable
    # Protocol itself just doesn't declare that, so mypy can't verify it.
    return Path(resource)  # type: ignore[arg-type]

_DEFAULT_CONFIG_RESOURCE = resource_files("cv_agent").joinpath("resources/default.toml")
_DEFAULT_REGISTRY_RESOURCE = resource_files("cv_agent").joinpath("resources/capability_registry.json")

def _default_config_path() -> Path | Traversable:
    return _DEFAULT_CONFIG_RESOURCE if _DEFAULT_CONFIG_RESOURCE.is_file() else _REPO_ROOT / "config" / "default.toml"


def _default_registry_path() -> Path | Traversable:
    return _DEFAULT_REGISTRY_RESOURCE if _DEFAULT_REGISTRY_RESOURCE.is_file() else _REPO_ROOT / "spec" / "capability_registry.json"


@dataclass(frozen=True)
class LLMBudgetConfig:
    """Daily budget and length limits (ADR-0020 §3.6, D-092); the defaults are the owner's decisions.
    Invalid values raise ``ValueError`` here and ``LLMConfigError`` when read from a file."""

    daily_usd_ceiling: float = 5.0
    daily_call_limit: int = 100
    max_input_chars: int = 24_000
    max_output_tokens: int = 4_000
    day_boundary_utc_offset: str = "+06:00"

    def __post_init__(self) -> None:
        if self.daily_usd_ceiling <= 0 or self.daily_call_limit < 1:
            raise ValueError("daily_usd_ceiling and daily_call_limit must be positive")
        if self.max_input_chars < 1 or self.max_output_tokens < 1:
            raise ValueError("max_input_chars and max_output_tokens must be positive")
        parse_utc_offset(self.day_boundary_utc_offset)


@dataclass(frozen=True)
class LLMPrivacyConfig:
    """Data classes (``DataClass`` member names) a hosted tier may receive; default-deny otherwise."""

    hosted_allowed_data_classes: tuple[str, ...] = ("PUBLIC_WEB", "PROJECT_METADATA")


@dataclass(frozen=True)
class LLMLogConfig:
    store_text: bool = False


def _default_routing() -> dict[str, str]:
    return {tc.value: "offline" for tc in TaskClass}


@dataclass
class LLMConfig:
    """Project LLM settings (ADR-0020 §3): routing, budget, privacy and log, nothing else.

    No provider or model is named here: ``routing`` maps a task class to a tier name, and the
    gateway-owned ``cv_agent/llm/catalog.toml`` says what each tier is. Every task class routes
    to ``offline`` until the owner changes it.
    """

    routing: dict[str, str] = field(default_factory=_default_routing)
    budget: LLMBudgetConfig = field(default_factory=LLMBudgetConfig)
    privacy: LLMPrivacyConfig = field(default_factory=LLMPrivacyConfig)
    log: LLMLogConfig = field(default_factory=LLMLogConfig)


@dataclass
class AgentConfig:
    """Top-level agent configuration."""

    llm: LLMConfig = field(default_factory=LLMConfig)
    registry_path: Path = field(
        default_factory=lambda: _resource_path("spec/capability_registry.json")
    )
    skill_paths: tuple[Path, ...] = field(default_factory=lambda: ())
    """Directories to scan for installed skills. Empty tuple means
    "use cv_agent.skills.local.default_skill_roots()" — kept empty here
    rather than duplicating that default, so there is exactly one place
    (local.py) that defines what "installed" means for this environment."""

    workspace_root: Optional[Path] = None
    """Explicit project/workspace root for durable Project Memory
    (ADR-0004). The calling application (the CLI's main(), or a caller
    constructing AgentConfig directly) is responsible for resolving this —
    AgentConfig neither reads it from a config file nor computes it here.
    None means "not provided"; CVAgent forwards it unchanged to
    cv_agent.memory.store.default_db_path(), whose own Path.cwd() fallback
    is a documented convenience for direct/standalone use only (ADR-0004
    §1 item 13, D-019) — not something this class invents a second copy
    of."""


def load_config(path: Optional[Path | Traversable] = None) -> AgentConfig:
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

    llm = _llm_from_raw(raw.get("llm", {}))

    registry_path_raw: Optional[str] = raw.get("registry_path")
    registry_path = (
        Path(registry_path_raw)
        if registry_path_raw
        else _resource_path("spec/capability_registry.json")
    )

    skill_paths_raw: list[str] = raw.get("skill_paths", [])
    skill_paths = tuple(Path(p) for p in skill_paths_raw)

    return AgentConfig(llm=llm, registry_path=registry_path, skill_paths=skill_paths)


# ── [llm] parsing: shape and values only; checks that need the catalog are in the router ──────


def _table(where: str, value: Any) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise LLMConfigError(f"{where} must be a table.")
    return value


def _only_keys(where: str, table: dict[str, Any], allowed: tuple[str, ...]) -> None:
    unknown = sorted(set(table) - set(allowed))
    if unknown:
        raise LLMConfigError(f"{where}: unknown key(s) {unknown}; allowed: {list(allowed)}.")


def _kind(where: str, key: str, value: Any, kinds: tuple[type, ...], label: str) -> None:
    if isinstance(value, bool) != (kinds == (bool,)) or not isinstance(value, kinds):
        raise LLMConfigError(f"{where}: {key} must be {label}, got {value!r}.")


def _llm_from_raw(raw: Any) -> LLMConfig:
    """Parse ``[llm]``; ``LLMConfigError`` for an unknown key anywhere or a bad value."""
    top = _table("[llm]", raw)
    _only_keys("[llm]", top, ("routing", "budget", "privacy", "log"))

    routing = _default_routing()
    given = _table("[llm.routing]", top.get("routing", {}))
    _only_keys("[llm.routing]", given, tuple(routing))
    for task_class, tier in given.items():
        _kind("[llm.routing]", task_class, tier, (str,), "a tier name")
        routing[task_class] = tier

    budget_raw = _table("[llm.budget]", top.get("budget", {}))
    _only_keys("[llm.budget]", budget_raw, tuple(f.name for f in fields(LLMBudgetConfig)))
    for key, kinds, label in (
        ("daily_usd_ceiling", (int, float), "a number"),
        ("daily_call_limit", (int,), "an integer"),
        ("max_input_chars", (int,), "an integer"),
        ("max_output_tokens", (int,), "an integer"),
        ("day_boundary_utc_offset", (str,), "a string like '+06:00'"),
    ):
        if key in budget_raw:
            _kind("[llm.budget]", key, budget_raw[key], kinds, label)
    try:
        budget = LLMBudgetConfig(**budget_raw)
    except ValueError as exc:
        raise LLMConfigError(f"[llm.budget]: {exc}") from exc

    privacy_raw = _table("[llm.privacy]", top.get("privacy", {}))
    _only_keys("[llm.privacy]", privacy_raw, ("hosted_allowed_data_classes",))
    privacy = LLMPrivacyConfig()
    if "hosted_allowed_data_classes" in privacy_raw:
        names = privacy_raw["hosted_allowed_data_classes"]
        if not isinstance(names, list) or not all(isinstance(n, str) for n in names):
            raise LLMConfigError("[llm.privacy]: hosted_allowed_data_classes must be a list of names.")
        unknown = sorted(set(names) - set(DataClass.__members__))
        if unknown:
            raise LLMConfigError(
                f"[llm.privacy]: unknown data class(es) {unknown}; known: {sorted(DataClass.__members__)}."
            )
        privacy = LLMPrivacyConfig(tuple(names))

    log_raw = _table("[llm.log]", top.get("log", {}))
    _only_keys("[llm.log]", log_raw, ("store_text",))
    if "store_text" in log_raw:
        _kind("[llm.log]", "store_text", log_raw["store_text"], (bool,), "true or false")
    return LLMConfig(routing, budget, privacy, LLMLogConfig(**log_raw))
