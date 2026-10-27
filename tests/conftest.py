from __future__ import annotations

import shutil
from collections.abc import Iterator
from pathlib import Path

import keyring
import pytest
from keyring.backend import KeyringBackend
from keyring.errors import PasswordDeleteError

from gitex import i18n
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
        "ANTHROPIC_API_KEY",
    ):
        monkeypatch.delenv(name, raising=False)
    # Testler varsayılan olarak Türkçe arayüzle çalışır (sistem dilinden bağımsız).
    monkeypatch.setenv("GITEX_LANG", "tr")
    i18n.reset()


class MemoryKeyring(KeyringBackend):
    """Gerçek işletim sistemi kasasına dokunmayan bellek içi kasa."""

    priority = 1

    def __init__(self) -> None:
        super().__init__()  # type: ignore[no-untyped-call]
        self.store: dict[tuple[str, str], str] = {}

    def get_password(self, service: str, username: str) -> str | None:
        return self.store.get((service, username))

    def set_password(self, service: str, username: str, password: str) -> None:
        self.store[(service, username)] = password

    def delete_password(self, service: str, username: str) -> None:
        if (service, username) not in self.store:
            raise PasswordDeleteError(username)
        del self.store[(service, username)]


@pytest.fixture(autouse=True)
def memory_keyring() -> Iterator[MemoryKeyring]:
    previous = keyring.get_keyring()
    kr = MemoryKeyring()
    keyring.set_keyring(kr)
    yield kr
    keyring.set_keyring(previous)


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
