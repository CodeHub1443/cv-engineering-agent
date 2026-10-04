"""
tests/trt_skill_contract.py — the installed trt-perf-analysis skill's contract, read from the skill.

The real-skill tests must track the skill that is actually installed, not a version hard-coded
in this repository (OPEN_QUESTIONS Q31 records the versioning question as open). Two facts are read
from the installed skill rather than assumed:

- the output ``schema_version`` it declares (the ``const`` in its own schema);
- its input contract: ``--data`` takes one layer-info JSON **and** one profile JSON, as a pair.

If the installed skill changes, these helpers follow it, so a real-skill test fails only when the
skill's own contract is violated, not when a repository constant is stale.
"""

from __future__ import annotations

import json
from pathlib import Path

from cv_agent.skills.local import LocalSkillSource

SKILL_ID = "trt-perf-analysis"


def installed_skill_location() -> Path:
    """The installed skill's SKILL.md, from the same discovery roots the repository uses."""
    for skill in LocalSkillSource().discover():
        if skill.skill_id == SKILL_ID:
            return Path(skill.location)
    raise AssertionError(f"{SKILL_ID} is not installed under the default skill roots")


def installed_schema_version() -> str:
    """The output schema_version the installed skill declares (its own schema's const)."""
    schema = installed_skill_location().parent / "schemas" / "analyze-data.schema.json"
    return json.loads(schema.read_text(encoding="utf-8"))["properties"]["schema_version"]["const"]


def write_profile_fixture(folder: Path, layers_path: Path, label: str) -> Path:
    """A profile_<label>.json with one timing record per layer in ``layers_path``.

    Matches the installed skill's rules (scripts/trt_perf/data.py::validate_profile and
    validate_names): a list of records, each with a non-empty string ``name`` and numeric
    ``timeMs``, ``averageMs``, ``medianMs`` and ``percentage``, and names that match the layers.
    """
    layers = json.loads(layers_path.read_text(encoding="utf-8"))
    names = [layer["Name"] for layer in layers]
    share = round(100 / len(names), 2)
    records = [
        {"name": n, "timeMs": 1.0, "averageMs": 1.0, "medianMs": 1.0, "percentage": share}
        for n in names
    ]
    path = folder / f"profile_{label}.json"
    path.write_text(json.dumps(records), encoding="utf-8")
    return path
