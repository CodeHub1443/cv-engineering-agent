"""Tests for cv_agent.config.settings."""

from __future__ import annotations

from pathlib import Path

import pytest

try:
    from importlib.resources.abc import Traversable  # Python 3.12+
except ImportError:  # pragma: no cover - exercised on Python < 3.12
    from importlib.abc import Traversable  # Python 3.10-3.11

from cv_agent.config.settings import AgentConfig, LLMConfig, LLMOverride, load_config


class TestLoadConfigDefaults:
    """load_config() with no file falls back to built-in defaults."""

    def test_returns_agent_config(self, tmp_path: Path) -> None:
        nonexistent = tmp_path / "does_not_exist.toml"
        cfg = load_config(nonexistent)
        assert isinstance(cfg, AgentConfig)

    def test_default_provider_is_mock(self, tmp_path: Path) -> None:
        cfg = load_config(tmp_path / "missing.toml")
        assert cfg.llm.provider == "mock"

    def test_default_model(self, tmp_path: Path) -> None:
        cfg = load_config(tmp_path / "missing.toml")
        assert cfg.llm.model == "fake-1"

    def test_no_overrides_by_default(self, tmp_path: Path) -> None:
        cfg = load_config(tmp_path / "missing.toml")
        assert cfg.llm.overrides == {}

    def test_registry_path_is_path_object(self, tmp_path: Path) -> None:
        cfg = load_config(tmp_path / "missing.toml")
        assert isinstance(cfg.registry_path, (Path, Traversable))
        assert cfg.registry_path.is_file()


class TestLoadConfigFromFile:
    """load_config() correctly parses a real TOML file."""

    def _write_toml(self, tmp_path: Path, content: str) -> Path:
        p = tmp_path / "test.toml"
        p.write_text(content, encoding="utf-8")
        return p

    def test_reads_provider_and_model(self, tmp_path: Path) -> None:
        p = self._write_toml(
            tmp_path,
            '[llm]\nprovider = "openai"\nmodel = "gpt-4o"\n',
        )
        cfg = load_config(p)
        assert cfg.llm.provider == "openai"
        assert cfg.llm.model == "gpt-4o"

    def test_reads_overrides(self, tmp_path: Path) -> None:
        p = self._write_toml(
            tmp_path,
            '[llm]\nprovider = "mock"\nmodel = "fake-1"\n'
            '[llm.overrides.planner]\nprovider = "anthropic"\nmodel = "claude-opus-4-5"\n',
        )
        cfg = load_config(p)
        assert "planner" in cfg.llm.overrides
        override = cfg.llm.overrides["planner"]
        assert isinstance(override, LLMOverride)
        assert override.provider == "anthropic"
        assert override.model == "claude-opus-4-5"

    def test_custom_registry_path(self, tmp_path: Path) -> None:
        custom = tmp_path / "my_registry.json"
        p = self._write_toml(
            tmp_path,
            f'registry_path = "{custom.as_posix()}"\n',
        )
        cfg = load_config(p)
        assert cfg.registry_path == custom

    def test_default_toml_is_valid(self) -> None:
        """The committed config/default.toml must be parseable."""
        cfg = load_config()  # uses default path
        assert cfg.llm.provider == "mock"
        assert cfg.llm.model == "fake-1"


class TestLLMConfig:
    def test_defaults(self) -> None:
        llm = LLMConfig()
        assert llm.provider == "mock"
        assert llm.model == "fake-1"
        assert llm.overrides == {}
