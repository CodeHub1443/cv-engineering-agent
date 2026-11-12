"""Tests for cv_agent.llm.credentials (ADR-0021 §3, slice C2).

Fake key strings only; every .env lives under tmp_path. The real project .env is never read.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path
from typing import Iterator

import pytest

from cv_agent.llm import credentials
from cv_agent.llm.credentials import (
    get_credential,
    load_project_env_file,
    note_env_file_not_searched,
    searched_locations,
)
from cv_agent.llm.errors import LLMCredentialError, LLMError

_VAR = "CV_AGENT_ANTHROPIC_API_KEY"
_FILE_VALUE = "test-not-a-real-key-from-file"
_ENV_VALUE = "test-not-a-real-key-from-env"


@pytest.fixture(autouse=True)
def _clean(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    credentials._reset_for_tests()
    monkeypatch.delenv(_VAR, raising=False)
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    yield
    credentials._reset_for_tests()


def _write(tmp_path: Path, text: str, mode: int = 0o600) -> Path:
    path = tmp_path / ".env"
    path.write_text(text, encoding="utf-8")
    path.chmod(mode)
    return path


def test_error_hierarchy() -> None:
    assert issubclass(LLMCredentialError, LLMError)
    assert issubclass(LLMError, RuntimeError)


def test_process_env_wins_over_dotenv(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    load_project_env_file(_write(tmp_path, f"{_VAR}={_FILE_VALUE}\n"))
    monkeypatch.setenv(_VAR, _ENV_VALUE)
    assert get_credential(_VAR) == _ENV_VALUE


def test_dotenv_used_when_env_absent(tmp_path: Path) -> None:
    load_project_env_file(_write(tmp_path, f"{_VAR}={_FILE_VALUE}\n"))
    assert get_credential(_VAR) == _FILE_VALUE


def test_parser_forms(tmp_path: Path) -> None:
    text = "\n".join(
        [
            "# a comment",
            "",
            "   ",
            "CV_AGENT_PLAIN=plain",
            "export CV_AGENT_EXPORTED=exported",
            'CV_AGENT_DQ="double quoted"',
            "CV_AGENT_SQ='single quoted'",
            "CV_AGENT_NOINTERP=$HOME/${OTHER}",
            "",
        ]
    )
    load_project_env_file(_write(tmp_path, text))
    assert get_credential("CV_AGENT_PLAIN") == "plain"
    assert get_credential("CV_AGENT_EXPORTED") == "exported"
    assert get_credential("CV_AGENT_DQ") == "double quoted"
    assert get_credential("CV_AGENT_SQ") == "single quoted"
    assert get_credential("CV_AGENT_NOINTERP") == "$HOME/${OTHER}"


def test_unmatched_quote_is_malformed(tmp_path: Path) -> None:
    path = _write(tmp_path, 'CV_AGENT_X="abc\n')
    with pytest.raises(LLMCredentialError) as info:
        load_project_env_file(path)
    assert ":1" in str(info.value)


def test_non_cv_agent_keys_are_dropped(tmp_path: Path) -> None:
    load_project_env_file(
        _write(
            tmp_path,
            "OTHER_KEY=x\nANTHROPIC_API_KEY=ignored\ncv_agent_lower=x\nCV_AGENT_OK=y\n",
        )
    )
    assert get_credential("CV_AGENT_OK") == "y"
    with pytest.raises(LLMCredentialError):
        get_credential(_VAR)
    assert set(credentials._LOADED) == {"CV_AGENT_OK"}


def test_malformed_line_names_path_and_line_not_content(tmp_path: Path) -> None:
    secret_line = "this-line-has-secret-sentinel-9f3"
    path = _write(tmp_path, f"# ok\n\n{secret_line}\n")
    with pytest.raises(LLMCredentialError) as info:
        load_project_env_file(path)
    text = str(info.value) + repr(info.value)
    assert f"{path}:3" in text
    assert "sentinel" not in text
    assert secret_line not in text


def test_load_does_not_touch_os_environ(tmp_path: Path) -> None:
    before = dict(os.environ)
    load_project_env_file(_write(tmp_path, f"{_VAR}={_FILE_VALUE}\nCV_AGENT_OTHER=1\n"))
    get_credential(_VAR)
    assert dict(os.environ) == before
    assert _VAR not in os.environ


def test_missing_key_error_names_variable_and_locations_no_value(tmp_path: Path) -> None:
    path = _write(tmp_path, "CV_AGENT_UNRELATED=sentinel-value-1\n")
    load_project_env_file(path)
    with pytest.raises(LLMCredentialError) as info:
        get_credential(_VAR)
    text = str(info.value) + repr(info.value)
    assert _VAR in text
    assert "environment" in text
    assert str(path) in text
    assert "sentinel-value-1" not in text


def test_ignored_by_design_message_never_leaks_value(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sentinel-generic-key-7c1")
    with pytest.raises(LLMCredentialError) as info:
        get_credential(_VAR)
    text = str(info.value) + repr(info.value)
    assert "ANTHROPIC_API_KEY is set but ignored by design (ADR-0021)." in text
    assert "sentinel-generic-key-7c1" not in text


def test_no_ignored_message_when_generic_key_unset() -> None:
    with pytest.raises(LLMCredentialError) as info:
        get_credential(_VAR)
    assert "ignored by design" not in str(info.value)


@pytest.mark.parametrize(
    "name", ["ANTHROPIC_API_KEY", "cv_agent_x", "CV_AGENT_", "CV_AGENT_a", "X_CV_AGENT_A", ""]
)
def test_get_credential_rejects_bad_names(name: str) -> None:
    with pytest.raises(LLMCredentialError):
        get_credential(name)


@pytest.mark.skipif(sys.platform == "win32", reason="POSIX permission bits only")
def test_posix_group_other_bits_refused(tmp_path: Path) -> None:
    path = _write(tmp_path, f"{_VAR}={_FILE_VALUE}\n", mode=0o644)
    with pytest.raises(LLMCredentialError, match="chmod 600") as info:
        load_project_env_file(path)
    assert _FILE_VALUE not in str(info.value)


@pytest.mark.skipif(sys.platform == "win32", reason="POSIX permission bits only")
def test_posix_mode_600_accepted(tmp_path: Path) -> None:
    load_project_env_file(_write(tmp_path, f"{_VAR}={_FILE_VALUE}\n", mode=0o600))
    assert get_credential(_VAR) == _FILE_VALUE


def test_root_unresolvable_only_env_searched() -> None:
    note_env_file_not_searched("not inside a git repository")
    assert any(".env not searched: not inside a git repository" in s for s in searched_locations())
    with pytest.raises(LLMCredentialError) as info:
        get_credential(_VAR)
    assert ".env not searched: not inside a git repository" in str(info.value)


def test_root_unresolvable_env_still_works(monkeypatch: pytest.MonkeyPatch) -> None:
    note_env_file_not_searched("reason")
    monkeypatch.setenv(_VAR, _ENV_VALUE)
    assert get_credential(_VAR) == _ENV_VALUE


def test_empty_value_counts_as_missing(tmp_path: Path) -> None:
    load_project_env_file(_write(tmp_path, f"{_VAR}=\n"))
    with pytest.raises(LLMCredentialError):
        get_credential(_VAR)


def test_unreadable_path_raises_credential_error(tmp_path: Path) -> None:
    with pytest.raises(LLMCredentialError):
        load_project_env_file(tmp_path / "nope.env")


def test_reset_clears_state(tmp_path: Path) -> None:
    load_project_env_file(_write(tmp_path, f"{_VAR}={_FILE_VALUE}\n"))
    credentials._reset_for_tests()
    with pytest.raises(LLMCredentialError):
        get_credential(_VAR)


# ── CLI wiring (ADR-0021 §3.5) ──────────────────────────────────────────────


def test_cli_loads_env_file_once_from_resolved_root(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, real_credential_loader: None
) -> None:
    import cv_agent.__main__ as cli
    import cv_agent.experiments.provenance as prov

    _write(tmp_path, f"{_VAR}={_FILE_VALUE}\n")
    monkeypatch.setattr(prov, "repository_state_root", lambda: tmp_path / ".cv_agent")
    cli._load_project_credentials()
    assert get_credential(_VAR) == _FILE_VALUE


def test_cli_missing_env_file_is_not_an_error(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, real_credential_loader: None
) -> None:
    import cv_agent.__main__ as cli
    import cv_agent.experiments.provenance as prov

    monkeypatch.setattr(prov, "repository_state_root", lambda: tmp_path / ".cv_agent")
    cli._load_project_credentials()
    assert any("does not exist" in s for s in searched_locations())


def test_cli_unresolvable_root_does_not_fail(
    monkeypatch: pytest.MonkeyPatch, real_credential_loader: None
) -> None:
    import cv_agent.__main__ as cli
    import cv_agent.experiments.provenance as prov

    def _boom() -> Path:
        raise prov.ProvenanceError("no git here")

    monkeypatch.setattr(prov, "repository_state_root", _boom)
    cli._load_project_credentials()
    assert any(".env not searched: project root not resolvable" in s for s in searched_locations())
