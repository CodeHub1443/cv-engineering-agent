"""Shared test fixtures.

Credential isolation (ADR-0021): no test may read the real project ``.env``. The CLI loads it
in ``main()``, so that loader is replaced by a no-op for every test, and the credential
module state is reset around each test. A test that exercises the real loader requests the
``real_credential_loader`` fixture and points the project root at a tmp_path.
"""

from __future__ import annotations

from typing import Iterator

import pytest


@pytest.fixture
def real_credential_loader() -> None:
    """Opt out of the autouse no-op below (marker fixture; does nothing itself)."""
    return None


@pytest.fixture(autouse=True)
def _isolate_credentials(
    request: pytest.FixtureRequest, monkeypatch: pytest.MonkeyPatch
) -> Iterator[None]:
    from cv_agent.llm import credentials

    credentials._reset_for_tests()
    if "real_credential_loader" not in request.fixturenames:
        import cv_agent.__main__ as cli

        monkeypatch.setattr(cli, "_load_project_credentials", lambda: None)
    yield
    credentials._reset_for_tests()
