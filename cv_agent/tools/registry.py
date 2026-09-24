"""
cv_agent.tools.registry — ToolRegistry + tool-pin validation.

See ADR-0005 §5. Deterministic, inspectable registry of specs and invokers,
mirroring `cv_agent.execution.binding.ExecutionBindingRegistry` (ADR-0009).
No `ToolSpec` or `ToolInvoker` is registered anywhere in this module — a
fresh `ToolRegistry()` starts, and stays, empty unless a caller explicitly
registers one.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from cv_agent.tools.invoker import ToolInvoker
from cv_agent.tools.models import (
    _APPROVAL_POLICIES,
    _GROUP_PIN_KEYS,
    _INPUT_FIELD_PIN_KEYS,
    _TOOL_SPEC_PIN_KEYS,
    _TOOL_TRANSPORTS,
    ToolId,
    ToolSpec,
    _json_native,
    canonical_json,
)


def _is_str_list(value: Any) -> bool:
    return isinstance(value, list) and all(isinstance(v, str) for v in value)


def _spec_shape_ok(spec: Any) -> bool:
    """Strict schema of a `ToolSpec.pin()` dict: exact keys, exact types, no
    extras. Never raises."""
    if not isinstance(spec, dict) or set(spec) != set(_TOOL_SPEC_PIN_KEYS):
        return False
    for key in ("tool_id", "name", "description"):
        if not isinstance(spec[key], str):
            return False
    if spec["transport"] not in _TOOL_TRANSPORTS:
        return False
    if not isinstance(spec["side_effecting"], bool):
        return False
    if spec["approval_policy"] not in _APPROVAL_POLICIES:
        return False
    if not isinstance(spec["verified"], bool):
        return False
    schema = spec["input_schema"]
    if not isinstance(schema, list):
        return False
    for entry in schema:
        if not isinstance(entry, dict) or set(entry) != set(_INPUT_FIELD_PIN_KEYS):
            return False
        if not isinstance(entry["name"], str) or not isinstance(entry["description"], str):
            return False
        if not isinstance(entry["required"], bool):
            return False
        _json_native(entry["default"])
    groups = spec["input_field_groups"]
    if not isinstance(groups, list):
        return False
    for group in groups:
        if not isinstance(group, dict) or set(group) != set(_GROUP_PIN_KEYS):
            return False
        if not isinstance(group["kind"], str) or not isinstance(group["description"], str):
            return False
        if not _is_str_list(group["field_names"]):
            return False
    return True


def _pin_shape_ok(pin: Any) -> bool:
    """Strict schema of a tool pin (`{"spec": ..., "invoker_generation":
    ...}`): exact keys, exact types, no extras. Never raises."""
    try:
        if not isinstance(pin, dict) or set(pin) != {"spec", "invoker_generation"}:
            return False
        generation = pin["invoker_generation"]
        if generation is not None and (type(generation) is not int or generation < 1):
            return False
        return _spec_shape_ok(pin["spec"])
    except (ValueError, TypeError):
        return False


def tool_pin_is_well_formed(pin: Any, *, tool_id: ToolId) -> bool:
    """`_pin_shape_ok` plus `spec.tool_id == tool_id` — mirrors
    `cv_agent.execution.binding.pin_is_well_formed` (ADR-0009 §14)."""
    return _pin_shape_ok(pin) and pin["spec"]["tool_id"] == tool_id


def tool_pin_mismatch(expected: Any, live: dict[str, Any]) -> tuple[str, ...]:
    """
    Compare a supplied pin with the live one. `()` means equal; a malformed
    `expected` is `("tool_pin_malformed",)`; otherwise sorted codes —
    `spec.<key>` per differing spec key, `invoker_registration` when the
    invoker generation differs. Equality is `canonical_json` of each value —
    the identical algorithm to `cv_agent.execution.binding.pin_mismatch`
    (ADR-0009 §14): two independently-typed but functionally identical
    checks, not two different security models (ADR-0005 §11 finding #2).
    """
    if not _pin_shape_ok(expected):
        return ("tool_pin_malformed",)
    codes: list[str] = []
    for key in _TOOL_SPEC_PIN_KEYS:
        if canonical_json(expected["spec"][key]) != canonical_json(live["spec"][key]):
            codes.append(f"spec.{key}")
    if canonical_json(expected["invoker_generation"]) != canonical_json(
        live["invoker_generation"]
    ):
        codes.append("invoker_registration")
    return tuple(sorted(codes))


@dataclass
class ToolRegistry:
    """
    Deterministic, inspectable registry of `ToolSpec`s and `ToolInvoker`s.

    Deterministic: lookups are exact dict gets, `list_specs()`/
    `list_invokers()` are sorted — no scoring, no fuzzy matching, no LLM.
    Inspectable: every registered spec and invoker can be listed without
    invoking anything.
    """

    _specs: dict[str, ToolSpec] = field(default_factory=dict, init=False, repr=False)
    _invokers: dict[str, tuple[ToolInvoker, int]] = field(
        default_factory=dict, init=False, repr=False
    )
    """tool_id -> (invoker, registration generation), replaced by a single
    assignment so instance and generation are always read together
    (ADR-0005 §5, mirrors ADR-0003 §10.8)."""

    def register_spec(self, spec: ToolSpec) -> None:
        self._specs[spec.tool_id] = spec

    def register_invoker(self, invoker: ToolInvoker) -> None:
        """Generation: first registration 1; the same object again keeps it
        (identical re-registration is not a change); a different object
        under the same `tool_id` increments it. Only this method maintains
        the generation — writing `_invokers` directly bypasses it. This is
        the mechanism that makes a replacement `ToolInvoker` during a paused
        workflow detectable (ADR-0005 §11 finding #1). No removal API exists
        and none is added, consistent with `ExecutionBindingRegistry`'s own
        documented limitation (ADR-0009 §14)."""
        prior = self._invokers.get(invoker.tool_id)
        if prior is None:
            generation = 1
        elif prior[0] is invoker:
            generation = prior[1]
        else:
            generation = prior[1] + 1
        self._invokers[invoker.tool_id] = (invoker, generation)

    def get_spec(self, tool_id: ToolId) -> ToolSpec | None:
        return self._specs.get(tool_id)

    def get_invoker(self, tool_id: ToolId) -> ToolInvoker | None:
        entry = self._invokers.get(tool_id)
        return entry[0] if entry is not None else None

    def get_invoker_registration(self, tool_id: ToolId) -> tuple[ToolInvoker, int] | None:
        """Inspect-only: the registered invoker and its generation from ONE
        dict read, so a caller that invokes this instance is invoking the
        instance whose generation it compared. Mirrors
        `ExecutionBindingRegistry.get_runtime_registration()` (ADR-0009 §14)."""
        return self._invokers.get(tool_id)

    def list_specs(self) -> list[ToolSpec]:
        return sorted(self._specs.values(), key=lambda s: s.tool_id)

    def list_invokers(self) -> list[ToolInvoker]:
        return sorted((e[0] for e in self._invokers.values()), key=lambda i: i.tool_id)

    def can_invoke(self, tool_id: ToolId) -> bool:
        """Inspect only — never invokes anything. True iff a verified spec
        with a registered invoker exists for tool_id."""
        spec = self._specs.get(tool_id)
        if spec is None or not spec.verified:
            return False
        return self._invokers.get(tool_id) is not None

    def pin(self, tool_id: ToolId) -> dict[str, Any] | None:
        """
        The tool pin for `tool_id` (ADR-0005 §5): `{"spec": spec.pin(),
        "invoker_generation": int | None}`, or `None` if no spec is
        registered. `invoker_generation` is `None` when no invoker is
        registered for `tool_id`. Raises `ValueError` if the spec cannot be
        pinned (non-JSON-native default). Mirrors
        `ExecutionBindingRegistry.pin(skill_id)` (ADR-0009 §14) exactly.
        """
        spec = self._specs.get(tool_id)
        if spec is None:
            return None
        registration = self._invokers.get(tool_id)
        return {
            "spec": spec.pin(),
            "invoker_generation": registration[1] if registration is not None else None,
        }
