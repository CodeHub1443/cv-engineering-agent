"""ADR-0023 §7.1 criterion 11 and amendment item 6 (slice S5, issue #140): structural tests on the AST.

- The schema constants ``SYSTEM`` and ``INSTRUCTIONS`` are string literals, never computed or reassigned.
- No provider or model string, and no provider SDK import, outside ``cv_agent/llm/``.
- Schema and vocabulary registration happens only at module top level of an allowlisted module. This is the
  backstop for the forged-``__name__`` gap accepted in the S1 amendment (item 6).

``KnowledgeItem(`` with ``ingest=`` is in ``test_knowledge_ingest_writers.py`` and the selector's import
boundary in ``test_selector_boundary.py`` (both S4).
"""

from __future__ import annotations

import ast
import re
from pathlib import Path

from cv_agent.llm.payload import SCHEMA_MODULES

ROOT = Path(__file__).resolve().parents[1] / "cv_agent"
_PROVIDER = re.compile(r"(?i)\b(anthropic|openai|gemini|mistral(ai)?|cohere|ollama|bedrock|litellm)\b")
_MODEL = re.compile(r"(?i)\b(claude-(opus|sonnet|haiku|fable|instant|\d)|gpt-\d|o[134]-(mini|preview)|gemini-\d|llama-?\d)")
_SDKS = ("anthropic", "openai", "google.generativeai", "google.genai", "mistralai", "cohere", "ollama", "litellm")
_REGISTER = {"register_schema", "register_vocabulary"}
_DEFINES_REGISTER = "llm/payload.py"


def _trees() -> list[tuple[str, ast.Module]]:
    return [(p.relative_to(ROOT).as_posix(), ast.parse(p.read_text(encoding="utf-8"))) for p in sorted(ROOT.rglob("*.py"))]


def _name(node: ast.AST) -> str:
    return node.id if isinstance(node, ast.Name) else node.attr if isinstance(node, ast.Attribute) else ""


# ── SYSTEM / INSTRUCTIONS are literals ───────────────────────────────────────


def _constant_problems(tree: ast.Module) -> list[str]:
    problems = []
    for node in ast.walk(tree):
        if isinstance(node, ast.ClassDef) and any(_name(d) == "register_schema" for d in node.decorator_list):
            bound = {}
            for stmt in node.body:
                target = stmt.targets[0] if isinstance(stmt, ast.Assign) else getattr(stmt, "target", None)
                if _name(target) in ("SYSTEM", "INSTRUCTIONS") and isinstance(stmt, (ast.Assign, ast.AnnAssign)):
                    bound[_name(target)] = stmt.value
            for const in ("SYSTEM", "INSTRUCTIONS"):
                value = bound.get(const)
                if not (isinstance(value, ast.Constant) and isinstance(value.value, str)):
                    problems.append(f"{node.name}.{const} is not a string literal")
        targets = node.targets if isinstance(node, ast.Assign) else [node.target] if isinstance(node, ast.AugAssign) else []
        problems += [f"line {node.lineno}: {t.attr} reassigned" for t in targets
                     if isinstance(t, ast.Attribute) and t.attr in ("SYSTEM", "INSTRUCTIONS")]
    return problems


def test_schema_constants_are_string_literals_and_never_reassigned() -> None:
    schemas = [rel for rel, tree in _trees() if any(isinstance(n, ast.ClassDef) and any(_name(d) == "register_schema" for d in n.decorator_list) for n in ast.walk(tree))]
    assert sorted(schemas) == ["model_selection/selection_payload.py", "requirements/structured.py"]
    bad = {rel: p for rel, tree in _trees() if (p := _constant_problems(tree))}
    assert not bad, bad


def test_the_literal_check_catches_computed_and_reassigned_constants() -> None:
    src = (
        "@register_schema\nclass A:\n    SYSTEM = f'x{y}'\n    INSTRUCTIONS = ('a' 'b')\n"
        "@register_schema\nclass B:\n    SYSTEM = NAME\n    INSTRUCTIONS = 'ok'\nB.INSTRUCTIONS = 'new'\n"
    )
    assert _constant_problems(ast.parse(src)) == [
        "A.SYSTEM is not a string literal", "B.SYSTEM is not a string literal", "line 9: INSTRUCTIONS reassigned",
    ]


# ── no provider or model string outside cv_agent/llm/ ────────────────────────


def _provider_hits(tree: ast.Module) -> list[str]:
    hits = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            if m := _PROVIDER.search(node.value) or _MODEL.search(node.value):
                hits.append(f"line {node.lineno}: {m.group(0)}")
        modules = [a.name for a in node.names] if isinstance(node, ast.Import) else [node.module or ""] if isinstance(node, ast.ImportFrom) else []
        hits += [f"line {node.lineno}: imports {m}" for m in modules if any(m == s or m.startswith(s + ".") for s in _SDKS)]
    return hits


def test_no_provider_or_model_string_outside_the_llm_package() -> None:
    bad = {rel: h for rel, tree in _trees() if not rel.startswith("llm/") and (h := _provider_hits(tree))}
    assert not bad, bad


def test_the_provider_check_catches_a_model_string_a_provider_name_and_an_sdk_import() -> None:
    src = 'import openai\nfrom anthropic import Anthropic\nM = "claude-opus-5-5"\nP = "use Gemini here"\nok = "Claude Code"\n'
    assert len(_provider_hits(ast.parse(src))) == 4


# ── registration only at top level of an allowlisted module ─────────────────


def _registrations(tree: ast.Module) -> list[tuple[str, int, bool]]:
    """``(name, line, at_top_level)`` for every reference to a register function, calls and decorators alike."""
    out = []

    def visit(node: ast.AST, nested: bool) -> None:
        if _name(node) in _REGISTER and isinstance(node, (ast.Name, ast.Attribute)):
            out.append((_name(node), node.lineno, not nested))
        for child in ast.iter_child_nodes(node):
            visit(child, nested or isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda)))

    visit(tree, False)
    return out


def test_registration_is_top_level_and_only_in_the_allowlisted_modules() -> None:
    allowed = {m.removeprefix("cv_agent.").replace(".", "/") + ".py" for m in SCHEMA_MODULES}
    found = {rel: regs for rel, tree in _trees() if rel != _DEFINES_REGISTER and (regs := _registrations(tree))}
    assert set(found) == allowed, "a module outside the schema allowlist references register_*"
    nested = {rel: [r for r in regs if not r[2]] for rel, regs in found.items()}
    assert not any(nested.values()), nested


def test_no_module_forges_its_name_or_executes_code_to_reach_the_registry() -> None:
    bad = []
    for rel, tree in _trees():
        for node in ast.walk(tree):
            targets = node.targets if isinstance(node, ast.Assign) else [node.target] if isinstance(node, (ast.AnnAssign, ast.AugAssign)) else []
            bad += [f"{rel}:{node.lineno} assigns __name__" for t in targets if _name(t) == "__name__"]
            bad += [f"{rel}:{node.lineno} {_name(node.func)}" for node in [node] if isinstance(node, ast.Call)
                    and _name(node.func) in ("exec", "run_module", "run_path")]
            if isinstance(node, ast.Subscript) and _name(node.value) == "__dict__" and isinstance(node.ctx, ast.Store):
                bad.append(f"{rel}:{node.lineno} writes a module __dict__")
    assert not bad, bad


def test_the_registration_check_sees_nested_calls_and_decorators() -> None:
    src = "@register_schema\nclass A: ...\ndef f():\n    register_vocabulary(v)\n    p.register_schema(c)\n"
    assert _registrations(ast.parse(src)) == [
        ("register_schema", 1, True), ("register_vocabulary", 4, False), ("register_schema", 5, False),
    ]
