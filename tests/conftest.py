from __future__ import annotations

import shutil
from collections.abc import Iterator
from pathlib import Path

import pytest

from gitex.evals.fixture import FixtureRepo, build_fixture_repo
from gitex.git.reader import GitRepo
from gitex.index.db import Database
from gitex.index.indexer import index_repo, open_index


@pytest.fixture(autouse=True)
def _isolated_env(
    monkeypatch: pytest.MonkeyPatch, tmp_path_factory: pytest.TempPathFactory
) -> None:
    """Testler kullanıcının gerçek config'ini ve sırlarını görmesin."""
    cfg_dir = tmp_path_factory.mktemp("usercfg")
    monkeypatch.setenv("GITEX_CONFIG", str(cfg_dir / "config.toml"))
    for name in (
        "GITEX_GITLAB_TOKEN",
        "GITEX_LLM_API_KEY",
        "GITEX_LLM_PROVIDER",
        "GITEX_LLM_MODEL",
        "GITEX_LLM_BASE_URL",
        "GITEX_LLM_MODE",
        "GITEX_GITLAB_URL",
        "GITEX_GITLAB_PROJECT",
    ):
        monkeypatch.delenv(name, raising=False)


@pytest.fixture(scope="session")
def _fixture_template(tmp_path_factory: pytest.TempPathFactory) -> FixtureRepo:
    return build_fixture_repo(tmp_path_factory.mktemp("template") / "repo")


@pytest.fixture
def fixture_repo(_fixture_template: FixtureRepo, tmp_path: Path) -> FixtureRepo:
    """Her test için şablon deponun kopyası (testler depoyu değiştirebilir)."""
    target = tmp_path / "repo"
    shutil.copytree(_fixture_template.path, target)
    return FixtureRepo(path=target, shas=dict(_fixture_template.shas))


@pytest.fixture
def repo(fixture_repo: FixtureRepo) -> GitRepo:
    return GitRepo(fixture_repo.path)


@pytest.fixture
def indexed_db(repo: GitRepo) -> Iterator[Database]:
    db = open_index(repo)
    index_repo(repo, db)
    yield db
    db.close()
