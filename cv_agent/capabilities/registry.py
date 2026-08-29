"""
cv_agent.capabilities.registry — Programmatic interface to the CV capability registry.

The registry is loaded from spec/capability_registry.json at runtime.
It represents relationships between capabilities, skills, tools, agents,
and knowledge sources — it does NOT implement or invoke those capabilities.

Public interface:
    registry.list()          → list[Capability]
    registry.describe(id)    → Capability
    registry.check(id)       → dict  (availability report)
    registry.select(task)    → list[Capability]  (available, matching task type)
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal, Optional
from importlib.resources.abc import Traversable

CapabilityStatus = Literal["available", "partial", "experimental", "unavailable"]
RiskLevel = Literal["low", "medium", "high"]
ItemType = Literal["skill", "tool", "agent", "knowledge_source"]


@dataclass(frozen=True)
class InputSpec:
    """Specification for a capability input parameter."""

    name: str
    type: str
    description: str


@dataclass(frozen=True)
class OutputSpec:
    """Specification for a capability output."""

    name: str
    type: str
    description: str


@dataclass(frozen=True)
class Capability:
    """
    A single CV engineering capability entry.

    Represents *what the agent needs to accomplish*, not how to do it.
    Skills, tools, agents, and knowledge sources are referenced by ID.
    """

    id: str
    name: str
    category: str
    description: str
    required_inputs: tuple[InputSpec, ...]
    outputs: tuple[OutputSpec, ...]
    relevant_skills: tuple[str, ...]
    relevant_tools: tuple[str, ...]
    relevant_agents: tuple[str, ...]
    knowledge_sources: tuple[str, ...]
    applicable_task_types: tuple[str, ...]
    prerequisites: tuple[str, ...]
    status: CapabilityStatus
    risk_level: RiskLevel

    @property
    def is_available(self) -> bool:
        return self.status in ("available", "partial")


@dataclass(frozen=True)
class RegistryItem:
    """
    A supporting entity referenced by capabilities.

    Item types:
        skill            — specialised procedural knowledge/instructions
        tool             — executable interface or program
        agent            — execution worker (Claude Code, Codex, …)
        knowledge_source — documentation, research, or reference material
    """

    id: str
    item_type: ItemType
    name: str
    description: str
    metadata: dict[str, Any] = field(default_factory=dict)


def _parse_capability(data: dict[str, Any]) -> Capability:
    return Capability(
        id=data["id"],
        name=data["name"],
        category=data["category"],
        description=data["description"],
        required_inputs=tuple(
            InputSpec(**s) for s in data.get("required_inputs", [])
        ),
        outputs=tuple(OutputSpec(**s) for s in data.get("outputs", [])),
        relevant_skills=tuple(data.get("relevant_skills", [])),
        relevant_tools=tuple(data.get("relevant_tools", [])),
        relevant_agents=tuple(data.get("relevant_agents", [])),
        knowledge_sources=tuple(data.get("knowledge_sources", [])),
        applicable_task_types=tuple(data.get("applicable_task_types", [])),
        prerequisites=tuple(data.get("prerequisites", [])),
        status=data.get("status", "unavailable"),
        risk_level=data.get("risk_level", "medium"),
    )


def _parse_item(data: dict[str, Any], item_type: ItemType) -> RegistryItem:
    core_keys = {"id", "name", "description"}
    return RegistryItem(
        id=data["id"],
        item_type=item_type,
        name=data["name"],
        description=data["description"],
        metadata={k: v for k, v in data.items() if k not in core_keys},
    )


class CapabilityRegistry:
    """
    Programmatic interface to the CV Agent capability registry.

    Availability is discovered from registry metadata — never assumed.
    Capability invocation is explicitly out of scope for this class.
    """

    def __init__(self, registry_path: Path | Traversable) -> None:
        self._path = registry_path
        self._capabilities: dict[str, Capability] = {}
        self._items: dict[tuple[ItemType, str], RegistryItem] = {}
        self._version: str = "unknown"
        self._loaded: bool = False

    # ── Loading ───────────────────────────────────────────────────────────

    def load(self) -> None:
        """
        Load the registry from disk.

        Raises:
            FileNotFoundError: If the registry JSON file does not exist.
            ValueError: If the JSON is structurally invalid.
        """
        if not self._path.is_file():
            raise FileNotFoundError(
                f"Capability registry not found: {self._path}\n"
                "Expected: spec/capability_registry.json relative to repo root."
            )

        with self._path.open("r", encoding="utf-8") as fh:
            raw: dict[str, Any] = json.load(fh)

        self._version = raw.get("version", "unknown")
        self._capabilities = {}
        for cap_data in raw.get("capabilities", []):
            cap = _parse_capability(cap_data)
            self._capabilities[cap.id] = cap

        self._items = {}
        type_map: dict[str, ItemType] = {
            "skills": "skill",
            "tools": "tool",
            "agents": "agent",
            "knowledge_sources": "knowledge_source",
        }
        for json_key, item_type in type_map.items():
            for item_data in raw.get(json_key, []):
                item = _parse_item(item_data, item_type)
                self._items[(item_type, item.id)] = item

        self._loaded = True

    def _ensure_loaded(self) -> None:
        if not self._loaded:
            self.load()

    # ── Public interface ──────────────────────────────────────────────────

    def list(
        self,
        *,
        category: Optional[str] = None,
        status: Optional[str] = None,
    ) -> list[Capability]:
        """
        List capabilities, optionally filtered.

        Args:
            category: Filter by category (e.g. 'evaluation', 'deployment').
            status:   Filter by status (e.g. 'available', 'experimental').

        Returns:
            Sorted list of matching Capability objects.
        """
        self._ensure_loaded()
        caps = list(self._capabilities.values())
        if category is not None:
            caps = [c for c in caps if c.category == category]
        if status is not None:
            caps = [c for c in caps if c.status == status]
        return sorted(caps, key=lambda c: c.id)

    def describe(self, capability_id: str) -> Capability:
        """
        Return full metadata for a capability.

        Args:
            capability_id: Dot-notation capability ID (e.g. 'cv.evaluation').

        Raises:
            KeyError: If the capability ID is not in the registry.
        """
        self._ensure_loaded()
        if capability_id not in self._capabilities:
            available = ", ".join(sorted(self._capabilities))
            raise KeyError(
                f"Unknown capability {capability_id!r}. "
                f"Registered: {available}"
            )
        return self._capabilities[capability_id]

    def check(self, capability_id: str) -> dict[str, Any]:
        """
        Check availability of a capability.

        Availability is derived from registry metadata — this method does
        not probe the environment or attempt to execute anything.

        Returns:
            dict with keys:
                capability_id   — the queried ID
                available       — bool (True if status is available/partial)
                status          — raw status string from registry
                risk_level      — risk level string
                reason          — human-readable explanation
                missing_prerequisites — list of prerequisite IDs whose
                                        status is not available/partial
        """
        self._ensure_loaded()
        cap = self.describe(capability_id)
        missing_prereqs = [
            p
            for p in cap.prerequisites
            if p in self._capabilities
            and not self._capabilities[p].is_available
        ]
        return {
            "capability_id": capability_id,
            "available": cap.is_available,
            "status": cap.status,
            "risk_level": cap.risk_level,
            "reason": f"Registry status is {cap.status!r}.",
            "missing_prerequisites": missing_prereqs,
        }

    def select(
        self,
        task_type: str,
        *,
        category: Optional[str] = None,
    ) -> list[Capability]:
        """
        Select available capabilities applicable to a given task type.

        Args:
            task_type: Task type tag (e.g. 'model_training', 'deployment').
            category:  Optional category filter.

        Returns:
            Sorted list of available Capability objects matching the task type.
        """
        self._ensure_loaded()
        results = [
            c
            for c in self._capabilities.values()
            if task_type in c.applicable_task_types
            and c.is_available
            and (category is None or c.category == category)
        ]
        return sorted(results, key=lambda c: c.id)

    def list_items(
        self,
        item_type: Optional[ItemType] = None,
    ) -> list[RegistryItem]:
        """
        List supporting registry items (skills, tools, agents, knowledge sources).

        Args:
            item_type: Optional filter ('skill', 'tool', 'agent', 'knowledge_source').
        """
        self._ensure_loaded()
        items = list(self._items.values())
        if item_type is not None:
            items = [i for i in items if i.item_type == item_type]
        return sorted(items, key=lambda i: (i.item_type, i.id))

    def describe_item(
        self,
        item_id: str,
        *,
        item_type: ItemType,
    ) -> RegistryItem:
        """Return a supporting registry item using type-aware identity."""
        self._ensure_loaded()
        key = (item_type, item_id)
        if key not in self._items:
            available = ", ".join(
                sorted(i.id for i in self._items.values() if i.item_type == item_type)
            )
            raise KeyError(
                f"Unknown {item_type} {item_id!r}. Registered: {available}"
            )
        return self._items[key]

    def check_item(self, item_id: str, *, item_type: ItemType) -> dict[str, Any]:
        """Return metadata and availability information for a supporting item."""
        item = self.describe_item(item_id, item_type=item_type)
        return {
            "item_id": item.id,
            "item_type": item.item_type,
            "available": True,
            "name": item.name,
        }

    @property
    def capability_count(self) -> int:
        """Number of registered capabilities."""
        self._ensure_loaded()
        return len(self._capabilities)

    @property
    def version(self) -> str:
        """Registry schema version string."""
        self._ensure_loaded()
        return self._version
