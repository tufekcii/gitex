from __future__ import annotations

import shutil
from collections.abc import Iterator
from pathlib import Path

import pytest

from gitsor.evals.fixture import FixtureRepo, build_fixture_repo
from gitsor.git.reader import GitRepo
from gitsor.index.db import Database
from gitsor.index.indexer import index_repo, open_index


@pytest.fixture(autouse=True)
def _isolated_env(
    monkeypatch: pytest.MonkeyPatch, tmp_path_factory: pytest.TempPathFactory
) -> None:
    """Testler kullanıcının gerçek config'ini ve sırlarını görmesin."""
    cfg_dir = tmp_path_factory.mktemp("usercfg")
    monkeypatch.setenv("GITSOR_CONFIG", str(cfg_dir / "config.toml"))
    for name in (
        "GITSOR_GITLAB_TOKEN",
        "GITSOR_LLM_API_KEY",
        "GITSOR_LLM_PROVIDER",
        "GITSOR_LLM_MODEL",
        "GITSOR_LLM_BASE_URL",
        "GITSOR_LLM_MODE",
        "GITSOR_GITLAB_URL",
        "GITSOR_GITLAB_PROJECT",
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
