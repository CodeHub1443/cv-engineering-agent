"""ADR-0023 §3.4, §7.1 criterion 11 (part), slice S4a: every writer sets ``ingest`` explicitly."""

from __future__ import annotations

import ast
from pathlib import Path

from cv_agent.graph.research import perform_research
from cv_agent.knowledge.models import IngestPath
from cv_agent.knowledge.store import InMemoryKnowledgeStore
from cv_agent.llm.mock import FakeLLMProvider
from cv_agent.llm.payload import PublicClaim
from cv_agent.model_selection.reference_task_research import build_reference_knowledge_store
from tests.test_research_orchestration import _llm_json, _make_executor, _minimal_request

ROOT = Path(__file__).resolve().parents[1] / "cv_agent"


def _aliases(tree: ast.AST) -> set[str]:
    """Every local name ``KnowledgeItem`` is bound to in a module, including ``import ... as`` aliases."""
    names = {"KnowledgeItem"}
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom):
            names |= {a.asname for a in node.names if a.name == "KnowledgeItem" and a.asname}
    return names


def _constructions() -> list[tuple[str, int, set[str]]]:
    out = []
    for path in sorted(ROOT.rglob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        names = _aliases(tree)
        for node in ast.walk(tree):
            if isinstance(node, ast.Call) and getattr(node.func, "id", getattr(node.func, "attr", "")) in names:
                out.append((path.relative_to(ROOT).as_posix(), node.lineno, {k.arg for k in node.keywords if k.arg}))
    return out


# Modules that call ``replace`` and import the knowledge models. A ``replace`` of a stored item would keep
# its ``ingest`` while changing its text, so each is reviewed: these two replace an LLMRequest and a config.
_REVIEWED_REPLACE = {"llm/payload.py", "__main__.py"}


def _replace_calls() -> set[str]:
    found = set()
    for path in sorted(ROOT.rglob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        imports_knowledge = any(
            isinstance(n, ast.ImportFrom) and (n.module or "").startswith("cv_agent.knowledge") for n in ast.walk(tree)
        )
        calls = any(
            isinstance(n, ast.Call) and getattr(n.func, "id", getattr(n.func, "attr", "")) == "replace"
            for n in ast.walk(tree)
        )
        if imports_knowledge and calls:
            found.add(path.relative_to(ROOT).as_posix())
    return found


def test_the_detector_sees_aliased_constructions() -> None:
    tree = ast.parse("from cv_agent.knowledge.models import KnowledgeItem as KI\nKI(item_id=1)")
    assert _aliases(tree) == {"KnowledgeItem", "KI"}


def test_no_unreviewed_replace_in_a_module_that_uses_knowledge_items() -> None:
    assert _replace_calls() <= _REVIEWED_REPLACE


def test_every_knowledge_item_construction_passes_ingest() -> None:
    found = _constructions()
    # The S4 writer inventory (ADR-0023 §7.2): these two modules author a KnowledgeItem. The third,
    # knowledge/sqlite_store.py (ADR-0024 K1b), only REBUILDS a stored row, passing the stored ingest
    # through unchanged; it sets no ingest of its own and the ``ingest`` keyword check below still covers it.
    assert {p for p, _, _ in found} == {
        "graph/research.py",
        "model_selection/reference_task_research.py",
        "knowledge/sqlite_store.py",
    }
    missing = [f"{p}:{line}" for p, line, kw in found if "ingest" not in kw]
    assert not missing, f"KnowledgeItem( without ingest=: {missing}"


def test_reference_store_items_are_curated_reference() -> None:
    items = build_reference_knowledge_store().list_items()
    assert items and {i.ingest for i in items} == {IngestPath.CURATED_REFERENCE}


def test_caller_supplied_conditions_never_become_web_text() -> None:
    """Review finding: ``ResearchRequest.conditions`` is a caller string. An item that used it as the
    fallback is not web text, so it must not be ingest=WEB_FETCH and must not reach a payload claim."""
    marker = "CANARY-caller-site-Plant7"
    executor, _ = _make_executor()
    store = InMemoryKnowledgeStore()
    result = perform_research(
        _minimal_request(conditions=marker),
        tool_executor=executor,
        llm_provider=FakeLLMProvider(fixed_response=_llm_json(conditions=None)),
        knowledge_store=store,
    )
    assert result.status == "stored" and result.knowledge_item is not None
    assert result.knowledge_item.ingest is IngestPath.PROJECT_INPUT
    assert not isinstance(PublicClaim.from_item(result.knowledge_item, ordinal=1, is_benchmark=False), PublicClaim)


def test_extracted_conditions_stay_web_fetch() -> None:
    executor, _ = _make_executor()
    result = perform_research(
        _minimal_request(conditions="caller fallback"),
        tool_executor=executor,
        llm_provider=FakeLLMProvider(fixed_response=_llm_json()),
        knowledge_store=InMemoryKnowledgeStore(),
    )
    assert result.knowledge_item is not None and result.knowledge_item.ingest is IngestPath.WEB_FETCH
    assert result.knowledge_item.conditions == "NVIDIA A100 GPU, batch size 32"
