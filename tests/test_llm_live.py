"""The one opt-in live LLM test (ADR-0020 G6, D-092). Owner-run only; see the PR for commands.

Skipped unless ``CV_AGENT_LIVE_LLM=1`` and ``CI`` is unset (tests/conftest.py). It makes ONE
real, paid call (a few hundredths of a cent) through the router and the real call log, so the
spend counts against the real daily budget. It prints the call id, stop reason, token counts
and settled USD only; never the key, the prompt or the response text.
"""

from __future__ import annotations

import dataclasses
import sqlite3

import pytest

from cv_agent.config.settings import load_config
from cv_agent.experiments.provenance import repository_state_root
from cv_agent.llm import credentials
from cv_agent.llm.base import LLMRequest
from cv_agent.llm.policy import DataClass, TaskClass
from cv_agent.llm.router import build_router
from cv_agent.llm.sqlite_store import LLM_CALLS_FILENAME

_SENTENCE = "The Eiffel Tower in Paris was completed in 1889 and is about 330 metres tall."


def _rows(db: str) -> list[sqlite3.Row]:
    con = sqlite3.connect(db)
    con.row_factory = sqlite3.Row
    try:
        return list(con.execute("SELECT * FROM llm_calls"))
    finally:
        con.close()


@pytest.mark.live_llm
def test_live_extraction_call_on_the_fast_tier(capsys: pytest.CaptureFixture[str]) -> None:
    state_root = repository_state_root()
    db = state_root / LLM_CALLS_FILENAME
    if not db.is_file():
        pytest.fail("LLM call log missing: run cv-agent llm-log init")
    assert len(_SENTENCE) < 200

    try:
        credentials.load_project_env_file(state_root.parent / ".env")
        llm = load_config().llm
        routing = {**llm.routing, TaskClass.EXTRACTION.value: "fast"}  # in memory only
        router = build_router(dataclasses.replace(llm, routing=routing), state_root)
        before = {r["call_id"] for r in _rows(str(db))}

        response = router.for_task(TaskClass.EXTRACTION).complete(
            LLMRequest(
                prompt=f"Extract the year from this sentence and reply with it only: {_SENTENCE}",
                max_tokens=64,
                data_classes=frozenset({DataClass.PUBLIC_WEB}),
            )
        )
    finally:
        credentials._reset_for_tests()

    assert response.content.strip()
    assert response.stop_reason == "end_turn"
    assert response.call_id
    new = [r for r in _rows(str(db)) if r["call_id"] not in before]
    assert len(new) == 1 and new[0]["call_id"] == response.call_id
    row = new[0]
    assert row["model"] == "claude-haiku-5-5"
    assert row["prompt_text"] is None
    con = sqlite3.connect(str(db))
    try:
        found = con.execute(
            "SELECT spent_usd, settled FROM llm_budget WHERE call_id = ?", (response.call_id,)
        ).fetchone()
    finally:
        con.close()
    assert found is not None and found[1] == 1
    spent = float(found[0])
    assert 0 < spent < 0.01
    with capsys.disabled():
        tokens = f"in={row['input_tokens']} out={row['output_tokens']}"
        print(f"\nlive: call_id={response.call_id} stop={response.stop_reason} {tokens} settled_usd={spent:.6f}")
