"""
Tests for cv_agent.skills (models, local discovery, inventory, resolver).

Every discovery test uses an isolated tmp_path fixture directory — never the
real machine's ~/.claude/skills — so results don't depend on what happens to
be installed on whoever runs the suite.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from cv_agent.capabilities.registry import CapabilityRegistry
from cv_agent.skills.inventory import SkillInventory
from cv_agent.skills.local import LocalSkillSource, _parse_frontmatter, default_skill_roots
from cv_agent.skills.models import Skill, SkillEvidence
from cv_agent.skills.resolver import TaskResolver

_REGISTRY_PATH = Path(__file__).parent.parent / "spec" / "capability_registry.json"


def _write_skill(root: Path, skill_id: str, *, frontmatter: str | None, body: str) -> Path:
    skill_dir = root / skill_id
    skill_dir.mkdir(parents=True, exist_ok=True)
    text = f"{frontmatter}\n{body}" if frontmatter else body
    (skill_dir / "SKILL.md").write_text(text, encoding="utf-8")
    return skill_dir


class TestFrontmatterParsing:
    def test_parses_flat_frontmatter(self) -> None:
        text = (
            "---\n"
            "name: deepstream-dev\n"
            "description: NVIDIA DeepStream SDK development.\n"
            "tags: deepstream, gstreamer\n"
            "---\n"
            "# body\n"
        )
        meta = _parse_frontmatter(text)
        assert meta["name"] == "deepstream-dev"
        assert meta["description"] == "NVIDIA DeepStream SDK development."
        assert meta["tags"] == "deepstream, gstreamer"

    def test_no_frontmatter_returns_empty_dict(self) -> None:
        """Real installed skills were found with no frontmatter at all
        (plain prose) — the parser must not crash or fabricate fields."""
        text = "You are a PyTorch and CUDA expert.\n\n## Section\n"
        assert _parse_frontmatter(text) == {}

    def test_malformed_frontmatter_does_not_raise(self) -> None:
        text = "---\nnot a key value line\n---\nbody"
        assert _parse_frontmatter(text) == {}


class TestLocalSkillSourceDiscovery:
    def test_discovers_skill_with_frontmatter(self, tmp_path: Path) -> None:
        _write_skill(
            tmp_path,
            "deepstream-dev",
            frontmatter="---\nname: deepstream-dev\ndescription: DeepStream pipelines.\ntags: deepstream\n---",
            body="# DeepStream",
        )
        source = LocalSkillSource(roots=(tmp_path,))
        skills = source.discover()
        assert len(skills) == 1
        assert skills[0].skill_id == "deepstream-dev"
        assert skills[0].name == "deepstream-dev"
        assert skills[0].description == "DeepStream pipelines."
        assert skills[0].tags == ("deepstream",)

    def test_discovers_skill_without_frontmatter(self, tmp_path: Path) -> None:
        _write_skill(tmp_path, "cuda-agent", frontmatter=None, body="You are a CUDA expert.\n")
        source = LocalSkillSource(roots=(tmp_path,))
        skills = source.discover()
        assert len(skills) == 1
        assert skills[0].skill_id == "cuda-agent"
        assert skills[0].name == "cuda-agent"  # falls back to dir name
        assert "CUDA expert" in skills[0].description

    def test_missing_root_yields_no_skills_not_an_error(self, tmp_path: Path) -> None:
        source = LocalSkillSource(roots=(tmp_path / "does_not_exist",))
        assert source.discover() == []

    def test_directory_without_skill_md_is_ignored(self, tmp_path: Path) -> None:
        (tmp_path / "not-a-skill").mkdir()
        (tmp_path / "not-a-skill" / "README.md").write_text("hello", encoding="utf-8")
        source = LocalSkillSource(roots=(tmp_path,))
        assert source.discover() == []

    def test_every_discovered_skill_is_not_executable(self, tmp_path: Path) -> None:
        """No execution binding exists anywhere yet — discovery alone must
        never claim executable=True."""
        _write_skill(tmp_path, "some-skill", frontmatter=None, body="body")
        source = LocalSkillSource(roots=(tmp_path,))
        skills = source.discover()
        assert all(s.executable is False for s in skills)
        assert all(s.discovered is True for s in skills)

    def test_duplicate_skill_id_across_roots_first_wins(self, tmp_path: Path) -> None:
        root_a = tmp_path / "a"
        root_b = tmp_path / "b"
        _write_skill(root_a, "dup-skill", frontmatter="---\nname: from-a\n---", body="a")
        _write_skill(root_b, "dup-skill", frontmatter="---\nname: from-b\n---", body="b")
        source = LocalSkillSource(roots=(root_a, root_b))
        skills = source.discover()
        assert len(skills) == 1
        assert skills[0].name == "from-a"

    def test_env_var_overrides_default_roots(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        _write_skill(tmp_path, "env-skill", frontmatter=None, body="body")
        monkeypatch.setenv("CV_AGENT_SKILL_PATHS", str(tmp_path))
        roots = default_skill_roots()
        assert roots == (tmp_path,)

    def test_default_roots_without_env_var(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("CV_AGENT_SKILL_PATHS", raising=False)
        roots = default_skill_roots()
        assert len(roots) == 2
        assert all(isinstance(r, Path) for r in roots)


class TestSkillInventory:
    def test_aggregates_multiple_sources(self, tmp_path: Path) -> None:
        root_a, root_b = tmp_path / "a", tmp_path / "b"
        _write_skill(root_a, "skill-a", frontmatter=None, body="a")
        _write_skill(root_b, "skill-b", frontmatter=None, body="b")
        inventory = SkillInventory(
            sources=(LocalSkillSource(roots=(root_a,)), LocalSkillSource(roots=(root_b,)))
        )
        ids = {s.skill_id for s in inventory.list()}
        assert ids == {"skill-a", "skill-b"}

    def test_get_missing_skill_returns_none_not_error(self, tmp_path: Path) -> None:
        inventory = SkillInventory(sources=(LocalSkillSource(roots=(tmp_path,)),))
        assert inventory.get("nonexistent-skill") is None
        assert inventory.is_discovered("nonexistent-skill") is False

    def test_get_discovered_skill(self, tmp_path: Path) -> None:
        _write_skill(tmp_path, "findable", frontmatter=None, body="x")
        inventory = SkillInventory(sources=(LocalSkillSource(roots=(tmp_path,)),))
        assert inventory.is_discovered("findable") is True
        skill = inventory.get("findable")
        assert isinstance(skill, Skill)
        assert isinstance(skill.evidence, SkillEvidence)


class TestTaskResolver:
    @pytest.fixture()
    def registry(self) -> CapabilityRegistry:
        reg = CapabilityRegistry(_REGISTRY_PATH)
        reg.load()
        return reg

    def test_resolve_with_no_discovered_skills_still_matches_capabilities(
        self, tmp_path: Path, registry: CapabilityRegistry
    ) -> None:
        inventory = SkillInventory(sources=(LocalSkillSource(roots=(tmp_path,)),))
        resolver = TaskResolver(capability_registry=registry, skill_inventory=inventory)
        result = resolver.resolve("optimize deployment on jetson")

        assert len(result.matched_capabilities) > 0
        assert result.matched_skills == ()  # nothing discovered
        assert any("no discovered skill" in w.lower() for w in result.warnings)

    def test_resolve_never_fabricates_a_missing_skill_as_matched(
        self, tmp_path: Path, registry: CapabilityRegistry
    ) -> None:
        """A skill declared relevant by a capability but not present on disk
        must show up in missing_skills, never in matched_skills."""
        inventory = SkillInventory(sources=(LocalSkillSource(roots=(tmp_path,)),))
        resolver = TaskResolver(capability_registry=registry, skill_inventory=inventory)
        result = resolver.resolve("deploy optimization on jetson tensorrt")

        matched_ids = {s.skill_id for s in result.matched_skills}
        assert matched_ids == set()  # nothing on disk in this fixture
        assert len(result.missing_skills) > 0

    def test_resolve_matches_a_discovered_skill(
        self, tmp_path: Path, registry: CapabilityRegistry
    ) -> None:
        _write_skill(
            tmp_path,
            "cuda-agent",
            frontmatter="---\nname: cuda-agent\ndescription: CUDA kernel optimization expert.\n---",
            body="",
        )
        inventory = SkillInventory(sources=(LocalSkillSource(roots=(tmp_path,)),))
        resolver = TaskResolver(capability_registry=registry, skill_inventory=inventory)
        result = resolver.resolve("optimize deployment for jetson using cuda kernels")

        matched_ids = {s.skill_id for s in result.matched_skills}
        assert "cuda-agent" in matched_ids
        cuda_match = next(s for s in result.matched_skills if s.skill_id == "cuda-agent")
        assert cuda_match.discovered is True
        assert cuda_match.executable is False

    def test_resolve_ranks_higher_overlap_first(
        self, tmp_path: Path, registry: CapabilityRegistry
    ) -> None:
        inventory = SkillInventory(sources=(LocalSkillSource(roots=(tmp_path,)),))
        resolver = TaskResolver(capability_registry=registry, skill_inventory=inventory)
        result = resolver.resolve("dataset audit and evaluation benchmarking")

        scores = [m.score for m in result.matched_capabilities]
        assert scores == sorted(scores, reverse=True)

    def test_empty_task_produces_no_matches_and_a_warning(
        self, tmp_path: Path, registry: CapabilityRegistry
    ) -> None:
        inventory = SkillInventory(sources=(LocalSkillSource(roots=(tmp_path,)),))
        resolver = TaskResolver(capability_registry=registry, skill_inventory=inventory)
        result = resolver.resolve("   ")
        assert result.matched_capabilities == ()
        assert len(result.warnings) > 0

    def test_unrelated_gibberish_task_matches_nothing(
        self, tmp_path: Path, registry: CapabilityRegistry
    ) -> None:
        inventory = SkillInventory(sources=(LocalSkillSource(roots=(tmp_path,)),))
        resolver = TaskResolver(capability_registry=registry, skill_inventory=inventory)
        result = resolver.resolve("xyzzy plugh qwertyzxcvbn")
        assert result.matched_capabilities == ()
        assert result.matched_skills == ()

    def test_no_capability_match_ever_reports_executable_status_as_available(
        self, tmp_path: Path, registry: CapabilityRegistry
    ) -> None:
        """Every capability in the registry is 'planned' — a resolution must
        never claim otherwise."""
        inventory = SkillInventory(sources=(LocalSkillSource(roots=(tmp_path,)),))
        resolver = TaskResolver(capability_registry=registry, skill_inventory=inventory)
        result = resolver.resolve("dataset audit evaluation benchmarking deployment jetson")
        assert len(result.matched_capabilities) > 0
        assert all(c.status == "planned" for c in result.matched_capabilities)
