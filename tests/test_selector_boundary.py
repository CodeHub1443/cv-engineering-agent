"""ADR-0023 §3.1, §7.1 criterion 11 (part), slice S4d (issue #132): the selector's import boundary.

The selector's boundary used to be ``knowledge.models`` and ``llm.base`` only (ADR-0014 §2). ADR-0023 §3.1
grants one narrow exception: ``cv_agent.requirements.structured.RequirementsView``, and nothing else from
requirements. Enforced on the AST (the ADR-0019 pattern), not on source lines.
"""

from __future__ import annotations

import ast
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1] / "cv_agent" / "model_selection"
STDLIB = {"__future__", "json", "re", "dataclasses", "types", "typing"}
SELECTOR_ALLOWED = STDLIB | {
    "cv_agent.knowledge.models",
    "cv_agent.llm.base",
    "cv_agent.llm.policy",
    "cv_agent.llm.payload",
    "cv_agent.model_selection.models",
    "cv_agent.model_selection.selection_payload",
    "cv_agent.requirements.structured",
}


def _imports(name: str) -> list[tuple[str, tuple[str, ...]]]:
    tree = ast.parse((ROOT / f"{name}.py").read_text(encoding="utf-8"))
    out: list[tuple[str, tuple[str, ...]]] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            out.extend((a.name, ()) for a in node.names)
        elif isinstance(node, ast.ImportFrom):
            assert node.level == 0, "relative imports are not used in cv_agent"
            out.append((node.module or "", tuple(a.name for a in node.names)))
    return out


def test_selector_imports_only_the_allowed_modules() -> None:
    bad = [m for m, _ in _imports("selector") if m not in SELECTOR_ALLOWED]
    assert not bad, f"selector imports outside its boundary: {bad}"


def test_selector_takes_only_requirements_view_from_requirements() -> None:
    names = [n for m, ns in _imports("selector") if m.startswith("cv_agent.requirements") for n in ns]
    assert names == ["RequirementsView"]
    # A plain ``import cv_agent.requirements...`` would reach every name in it, so it is not allowed.
    plain = [m for m, ns in _imports("selector") if m.startswith("cv_agent.requirements") and not ns]
    assert plain == []


def test_selector_has_no_dynamic_imports() -> None:
    tree = ast.parse((ROOT / "selector.py").read_text(encoding="utf-8"))
    dynamic = [
        n.lineno
        for n in ast.walk(tree)
        if isinstance(n, ast.Call) and getattr(n.func, "id", getattr(n.func, "attr", "")) in ("__import__", "import_module")
    ]
    assert dynamic == []


def test_selector_declares_no_data_class_itself() -> None:
    """The payload type decides the data classes; the selector has no label to write."""
    names = {n for _, ns in _imports("selector") for n in ns}
    assert "DataClass" not in names
    assert "PROJECT_DATA" not in (ROOT / "selector.py").read_text(encoding="utf-8")


def test_selection_payload_stays_inside_the_model_selection_and_gateway_boundary() -> None:
    allowed = STDLIB | {
        "cv_agent.llm.payload",
        "cv_agent.llm.policy",
        "cv_agent.model_selection.models",
        "cv_agent.requirements.structured",
    }
    bad = [m for m, _ in _imports("selection_payload") if m not in allowed]
    assert not bad, f"selection_payload imports outside its boundary: {bad}"


def test_the_boundary_check_would_catch_a_forbidden_import() -> None:
    tree = ast.parse("from cv_agent.requirements.analyzer import RequirementsAnalyzer\nimport cv_agent.graph")
    found = [n.module for n in ast.walk(tree) if isinstance(n, ast.ImportFrom)] + [
        a.name for n in ast.walk(tree) if isinstance(n, ast.Import) for a in n.names
    ]
    assert [m for m in found if m not in SELECTOR_ALLOWED] == ["cv_agent.requirements.analyzer", "cv_agent.graph"]
