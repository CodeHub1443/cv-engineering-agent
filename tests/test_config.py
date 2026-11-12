"""Tests for cv_agent.config.settings."""

from __future__ import annotations

from pathlib import Path

try:
    from importlib.resources.abc import Traversable  # Python 3.12+
except ImportError:  # pragma: no cover - exercised on Python < 3.12
    from importlib.abc import Traversable  # Python 3.10-3.11

from cv_agent.config.settings import AgentConfig, LLMConfig, load_config


class TestLoadConfigDefaults:
    """load_config() with no file falls back to built-in defaults."""

    def test_returns_agent_config(self, tmp_path: Path) -> None:
        nonexistent = tmp_path / "does_not_exist.toml"
        cfg = load_config(nonexistent)
        assert isinstance(cfg, AgentConfig)

    def test_every_route_is_offline_by_default(self, tmp_path: Path) -> None:
        cfg = load_config(tmp_path / "missing.toml")
        assert set(cfg.llm.routing.values()) == {"offline"}
        assert set(cfg.llm.routing) == {"extraction", "selection", "narrative"}

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

    def test_reads_routing(self, tmp_path: Path) -> None:
        p = self._write_toml(tmp_path, '[llm.routing]\nextraction = "fast"\n')
        cfg = load_config(p)
        assert cfg.llm.routing["extraction"] == "fast"
        assert cfg.llm.routing["narrative"] == "offline"

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
        assert cfg.llm == LLMConfig()
        assert set(cfg.llm.routing.values()) == {"offline"}

    def test_both_default_toml_copies_are_identical(self) -> None:
        root = Path(__file__).resolve().parents[1]
        top = (root / "config" / "default.toml").read_bytes()
        packaged = (root / "cv_agent" / "resources" / "config" / "default.toml").read_bytes()
        assert top == packaged

    def test_no_provider_or_model_string_in_config_files(self) -> None:
        """ADR-0020 §3.2 / CLAUDE.md §3.8: only the gateway catalog names a provider or model."""
        root = Path(__file__).resolve().parents[1]
        files = [
            root / "config" / "default.toml",
            root / "cv_agent" / "resources" / "config" / "default.toml",
            *sorted((root / "cv_agent" / "config").glob("*.py")),
        ]
        assert len(files) >= 3
        for f in files:
            text = f.read_text(encoding="utf-8").lower()
            assert "claude-" not in text, f
            assert "anthropic" not in text, f


class TestLLMConfig:
    def test_defaults(self) -> None:
        llm = LLMConfig()
        assert llm.routing == {"extraction": "offline", "selection": "offline", "narrative": "offline"}
        assert llm.budget.daily_usd_ceiling == 5.0
        assert llm.privacy.hosted_allowed_data_classes == ("PUBLIC_WEB", "PROJECT_METADATA")
        assert llm.log.store_text is False
