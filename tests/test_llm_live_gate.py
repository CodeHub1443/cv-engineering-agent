"""Self-tests of the ``live_llm`` gate in conftest.py (no network, no key)."""

from __future__ import annotations

from pathlib import Path

import pytest

from tests.conftest import _live_llm_skip_reason

_PROBE = """
import pytest

@pytest.mark.live_llm
def test_probe():
    pass
"""


def _outcome(pytester: pytest.Pytester, monkeypatch: pytest.MonkeyPatch, **env: str) -> pytest.RunResult:
    monkeypatch.delenv("CI", raising=False)
    monkeypatch.delenv("CV_AGENT_LIVE_LLM", raising=False)
    for k, v in env.items():
        monkeypatch.setenv(k, v)
    pytester.makeconftest(Path(__file__).with_name("conftest.py").read_text(encoding="utf-8"))
    pytester.makepyprojecttoml('[tool.pytest.ini_options]\nmarkers = ["live_llm: x"]\n')
    pytester.makepyfile(test_probe=_PROBE)
    return pytester.runpytest_subprocess("-p", "no:cacheprovider", "-rs")


pytest_plugins = ["pytester"]


def test_skipped_by_default(pytester: pytest.Pytester, monkeypatch: pytest.MonkeyPatch) -> None:
    _outcome(pytester, monkeypatch).assert_outcomes(skipped=1)


def test_runs_when_opted_in(pytester: pytest.Pytester, monkeypatch: pytest.MonkeyPatch) -> None:
    _outcome(pytester, monkeypatch, CV_AGENT_LIVE_LLM="1").assert_outcomes(passed=1)


def test_skipped_when_ci_is_set_even_if_opted_in(
    pytester: pytest.Pytester, monkeypatch: pytest.MonkeyPatch
) -> None:
    _outcome(pytester, monkeypatch, CV_AGENT_LIVE_LLM="1", CI="true").assert_outcomes(skipped=1)


def test_reason_function() -> None:
    assert _live_llm_skip_reason({}) is not None
    assert _live_llm_skip_reason({"CV_AGENT_LIVE_LLM": "0"}) is not None
    assert _live_llm_skip_reason({"CV_AGENT_LIVE_LLM": "1", "CI": "1"}) is not None
    assert _live_llm_skip_reason({"CV_AGENT_LIVE_LLM": "1"}) is None
