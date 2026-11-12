"""Structural guards for the LLM credential rules (ADR-0021 §3.4, §3.8, slice C2)."""

from __future__ import annotations

import ast
import re
from pathlib import Path

import cv_agent

_PACKAGE_ROOT = Path(cv_agent.__file__).parent
_MUTATORS = {"update", "setdefault", "pop", "popitem", "clear"}


def _is_os_environ(node: ast.AST) -> bool:
    return (
        isinstance(node, ast.Attribute)
        and node.attr == "environ"
        and isinstance(node.value, ast.Name)
        and node.value.id == "os"
    )


def _environ_writes(tree: ast.AST) -> list[int]:
    lines: list[int] = []
    for node in ast.walk(tree):
        if isinstance(node, (ast.Assign, ast.AugAssign, ast.AnnAssign, ast.Delete)):
            targets = node.targets if isinstance(node, (ast.Assign, ast.Delete)) else [node.target]
            for t in targets:
                if isinstance(t, ast.Subscript) and _is_os_environ(t.value):
                    lines.append(node.lineno)
        elif isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
            if _is_os_environ(node.func.value) and node.func.attr in _MUTATORS:
                lines.append(node.lineno)
            elif (
                node.func.attr in {"putenv", "unsetenv"}
                and isinstance(node.func.value, ast.Name)
                and node.func.value.id == "os"
            ):
                lines.append(node.lineno)
    return lines


def test_no_module_writes_os_environ() -> None:
    offenders = []
    for py in _PACKAGE_ROOT.rglob("*.py"):
        tree = ast.parse(py.read_text(encoding="utf-8"), filename=str(py))
        for line in _environ_writes(tree):
            offenders.append(f"{py.relative_to(_PACKAGE_ROOT)}:{line}")
    assert offenders == [], f"os.environ written: {offenders}"


def test_environ_write_detector_catches_writes() -> None:
    src = (
        "import os\n"
        "os.environ['A'] = 'b'\n"
        "os.environ.update({})\n"
        "os.environ.setdefault('A', 'b')\n"
        "os.putenv('A', 'b')\n"
    )
    assert len(_environ_writes(ast.parse(src))) == 4


def test_generic_anthropic_key_name_only_in_credentials_module() -> None:
    pattern = re.compile(r"(?<![A-Z0-9_])ANTHROPIC_API_KEY")
    offenders = [
        py.relative_to(_PACKAGE_ROOT).as_posix()
        for py in _PACKAGE_ROOT.rglob("*.py")
        if pattern.search(py.read_text(encoding="utf-8"))
    ]
    assert offenders == ["llm/credentials.py"]
