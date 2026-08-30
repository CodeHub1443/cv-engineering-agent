"""
cv_agent.capabilities.registry — Programmatic interface to the CV capability registry.

The registry is loaded from a packaged capability_registry.json at runtime,
with repository-checkout fallback. It represents relationships between
capabilities, skills, tools, agents, and knowledge sources — it does NOT
implement or invoke those capabilities.

Public interface:
    registry.list()          → list[Capability]
    registry.describe(id)    → Capability
    registry.check(id)       → dict  (availability report)
    registry.select(task)    → list[Capability]  (available, matching task type)
"""

from __future__ import annotations

import builtins
import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal

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
    """A single CV engineering capability entry."""

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
    """A supporting entity referenced by capabilities."""

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
        required_inputs=tuple(InputSpec(**s) for s in data.get("required_inputs", [])),
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
    """Programmatic interface to the CV Agent capability registry."""

    def __init__(self, registry_path: Path | Any) -> None:
        self._path = registry_path
        self._capabilities: dict[str, Capability] = {}
        self._items: dict[tuple[ItemType, str], RegistryItem] = {}
        self._version: str = "unknown"
        self._loaded: bool = False

    def load(self) -> None:
        """Load the registry from the configured path/resource."""
        if not self._path.is_file():
            raise FileNotFoundError(
                f"Capability registry resource could not be loaded: {self._path}"
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
                self._items[(item.item_type, item.id)] = item

        self._loaded = True

    def _ensure_loaded(self) -> None:
        if not self._loaded:
            self.load()

    def list(
        self, *, category: str | None = None, status: str | None = None
    ) -> builtins.list[Capability]:
        self._ensure_loaded()
        caps = list(self._capabilities.values())
        if category is not None:
            caps = [c for c in caps if c.category == category]
        if status is not None:
            caps = [c for c in caps if c.status == status]
        return sorted(caps, key=lambda c: c.id)

    def describe(self, capability_id: str) -> Capability:
        self._ensure_loaded()
        if capability_id not in self._capabilities:
            available = ", ".join(sorted(self._capabilities))
            raise KeyError(
                f"Unknown capability {capability_id!r}. Registered: {available}"
            )
        return self._capabilities[capability_id]

    def check(self, capability_id: str) -> dict[str, Any]:
        self._ensure_loaded()
        cap = self.describe(capability_id)
        missing_prereqs = [
            p
            for p in cap.prerequisites
            if p in self._capabilities and not self._capabilities[p].is_available
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
        self, task_type: str, *, category: str | None = None
    ) -> builtins.list[Capability]:
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
        self, item_type: ItemType | None = None
    ) -> builtins.list[RegistryItem]:
        self._ensure_loaded()
        items = list(self._items.values())
        if item_type is not None:
            items = [i for i in items if i.item_type == item_type]
        return sorted(items, key=lambda i: (i.item_type, i.id))

    def describe_item(self, item_type: ItemType, item_id: str) -> RegistryItem:
        """Return a supporting registry item using its type-safe identity."""
        self._ensure_loaded()
        key = (item_type, item_id)
        if key not in self._items:
            available = ", ".join(
                sorted(i.id for i in self._items.values() if i.item_type == item_type)
            )
            raise KeyError(f"Unknown {item_type} {item_id!r}. Registered: {available}")
        return self._items[key]

    def check_item(self, item_type: ItemType, item_id: str) -> dict[str, Any]:
        """Report the presence of a typed registry item without probing it."""
        item = self.describe_item(item_type, item_id)
        return {
            "item_id": item.id,
            "item_type": item.item_type,
            "available": True,
        }

    @property
    def capability_count(self) -> int:
        self._ensure_loaded()
        return len(self._capabilities)

    @property
    def version(self) -> str:
        self._ensure_loaded()
        return self._version
