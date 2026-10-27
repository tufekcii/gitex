from __future__ import annotations

from collections.abc import Iterator
from datetime import UTC, datetime

import pytest
import responses

from gitsor.agent.citations import CitationVerifier
from gitsor.agent.tools import Toolbox
from gitsor.config import Config, GitLabConfig
from gitsor.errors import GitLabError
from gitsor.evals.fixture import FixtureRepo
from gitsor.git.reader import GitRepo
from gitsor.gitlab.client import GitLabClient
from gitsor.gitlab.sync import sync_gitlab
from gitsor.index.db import Database
from gitsor.index.search import FTSSearch, MRQuery
from tests.gitlab_mock import BASE, PROJECT, GitLabMock, scenario


@pytest.fixture
def rsps() -> Iterator[responses.RequestsMock]:
    with responses.RequestsMock(assert_all_requests_are_fired=False) as r:
        yield r


def _client(per_page: int = 100) -> GitLabClient:
    return GitLabClient(
        GitLabConfig(url=BASE, project=PROJECT, per_page=per_page, max_retries=3), "dummy"
    )


def _fixed(ts: str):
    return lambda: datetime.fromisoformat(ts).replace(tzinfo=UTC)


def test_full_sync(
    rsps: responses.RequestsMock, indexed_db: Database, fixture_repo: FixtureRepo
) -> None:
    mock = GitLabMock(scenario(fixture_repo))
    mock.install(rsps)
    stats = sync_gitlab(_client(), indexed_db, now=_fixed("2026-05-01T00:00:00"))
    assert (stats.synced, stats.removed) == (3, 0)
    assert stats.notes == 2  # sistem notu hariç
    assert indexed_db.count("merge_requests") == 3
    assert indexed_db.get_meta("gitlab_last_sync") == "2026-05-01T00:00:00+00:00"
    search = FTSSearch(indexed_db)
    mr1 = search.get_mr(1)
    assert mr1 is not None
    assert mr1.commits == [fixture_repo.sha("refund")]
    diff_note = next(n for n in mr1.notes if n["file_path"])
    assert (diff_note["file_path"], diff_note["line"]) == ("payment/service.py", 12)
    assert mr1.issues[0]["iid"] == 7
    assert mr1.issues[0]["labels"] == ["müşteri", "ödeme"]
    assert mr1.issues[0]["relation"] == "closes"
    assert search.get_mr(4) is None  # kapatılmış (merge edilmemiş) MR alınmaz


def test_sha_to_mr_mapping(
    rsps: responses.RequestsMock, indexed_db: Database, fixture_repo: FixtureRepo
) -> None:
    GitLabMock(scenario(fixture_repo)).install(rsps)
    sync_gitlab(_client(), indexed_db)
    search = FTSSearch(indexed_db)
    # MR commit'i ve merge commit'i aynı MR'a eşlenir.
    assert [m.iid for m in search.mrs_for_commit(fixture_repo.sha("refund"))] == [1]
    assert [m.iid for m in search.mrs_for_commit(fixture_repo.sha("merge_refund"))] == [1]
    # Squash: main'deki squash commit'i MR'a eşlenir.
    assert [m.iid for m in search.mrs_for_commit(fixture_repo.sha("soft_delete"))] == [2]
    assert search.mrs_for_commit(fixture_repo.sha("init")) == []


def test_mr_search_sources(
    rsps: responses.RequestsMock, indexed_db: Database, fixture_repo: FixtureRepo
) -> None:
    GitLabMock(scenario(fixture_repo)).install(rsps)
    sync_gitlab(_client(), indexed_db)
    search = FTSSearch(indexed_db)
    hits = search.search_mrs(MRQuery(text="iade"))
    assert hits[0].iid == 1
    assert "mr" in hits[0].matched_in
    by_note = search.search_mrs(MRQuery(text="tutar kontrolu"))
    assert [h.iid for h in by_note] == [1]
    assert by_note[0].matched_in == ("note",)
    by_issue = search.search_mrs(MRQuery(text="KVKK denetimi"))
    assert by_issue[0].iid == 2
    assert search.search_mrs(MRQuery(state="opened"))[0].iid == 3


def test_incremental_sync(
    rsps: responses.RequestsMock, indexed_db: Database, fixture_repo: FixtureRepo
) -> None:
    data = scenario(fixture_repo)
    mock = GitLabMock(data)
    mock.install(rsps)
    sync_gitlab(_client(), indexed_db, now=_fixed("2026-05-01T00:00:00"))
    assert "updated_after" not in mock.list_queries[-1]

    # !1 başlığı değişti, !3 kapatıldı; diğerleri değişmedi.
    data[1]["mr"]["title"] = "Refund desteği (yeniden adlandırıldı)"
    data[1]["mr"]["updated_at"] = "2026-05-02T00:00:00Z"
    data[3]["mr"]["state"] = "closed"
    data[3]["mr"]["updated_at"] = "2026-05-03T00:00:00Z"
    stats = sync_gitlab(_client(), indexed_db, now=_fixed("2026-05-04T00:00:00"))
    assert mock.list_queries[-1]["updated_after"] == ["2026-05-01T00:00:00+00:00"]
    assert (stats.synced, stats.removed, stats.full) == (1, 1, False)
    search = FTSSearch(indexed_db)
    assert search.get_mr(3) is None
    mr1 = search.get_mr(1)
    assert mr1 is not None
    assert mr1.title.startswith("Refund")
    assert [h.iid for h in search.search_mrs(MRQuery(text="yeniden adlandirildi"))] == [1]
    assert len(mr1.notes) == 2  # yeniden yazımda yorumlar çoğalmamalı
    assert indexed_db.get_meta("gitlab_last_sync") == "2026-05-04T00:00:00+00:00"


def test_project_change_forces_full(
    rsps: responses.RequestsMock, indexed_db: Database, fixture_repo: FixtureRepo
) -> None:
    GitLabMock(scenario(fixture_repo)).install(rsps)
    indexed_db.set_meta("gitlab_project", "baska/proje")
    indexed_db.set_meta("gitlab_last_sync", "2030-01-01T00:00:00+00:00")
    stats = sync_gitlab(_client(), indexed_db)
    assert stats.full
    assert stats.synced == 3


def test_pagination(
    rsps: responses.RequestsMock, indexed_db: Database, fixture_repo: FixtureRepo
) -> None:
    mock = GitLabMock(scenario(fixture_repo), per_page=1)
    mock.install(rsps)
    stats = sync_gitlab(_client(per_page=1), indexed_db)
    assert stats.synced == 3
    assert len(mock.list_queries) == 4


def test_rate_limit_backoff(
    rsps: responses.RequestsMock, indexed_db: Database, fixture_repo: FixtureRepo
) -> None:
    mock = GitLabMock(scenario(fixture_repo), fail_first_with=429)
    mock.install(rsps)
    stats = sync_gitlab(_client(), indexed_db)
    assert stats.synced == 3


def test_auth_error(
    rsps: responses.RequestsMock, indexed_db: Database, fixture_repo: FixtureRepo
) -> None:
    GitLabMock(scenario(fixture_repo), status_override=401).install(rsps)
    with pytest.raises(GitLabError) as exc:
        sync_gitlab(_client(), indexed_db)
    assert exc.value.hint is not None
    assert "GITSOR_GITLAB_TOKEN" in exc.value.hint


# ---------------------------------------------------------------------- araçlar


@pytest.fixture
def gl_toolbox(
    rsps: responses.RequestsMock, repo: GitRepo, indexed_db: Database, fixture_repo: FixtureRepo
) -> Toolbox:
    GitLabMock(scenario(fixture_repo)).install(rsps)
    sync_gitlab(_client(), indexed_db)
    cfg = Config.model_validate({"gitlab": {"url": BASE, "project": PROJECT}})
    return Toolbox(repo, indexed_db, cfg)


def test_gitlab_tools(gl_toolbox: Toolbox, fixture_repo: FixtureRepo) -> None:
    assert {"search_mrs", "get_mr"} <= {s.name for s in gl_toolbox.specs()}
    out = gl_toolbox.execute("get_mr", {"iid": 1}).text
    assert "Müşteri hizmetleri manuel iade" in out
    assert "tutar kontrolü eksik" in out
    assert "(payment/service.py:12)" in out
    assert "#7 (closes) Müşteriler iade alamıyor" in out
    commit = gl_toolbox.execute("get_commit", {"sha": fixture_repo.sha("soft_delete")}).text
    assert "bağlı MR: !2" in commit
    found = gl_toolbox.execute("search_mrs", {"query": "iade"}).text
    assert "!1" in found


def test_mr_citations(gl_toolbox: Toolbox) -> None:
    verifier = CitationVerifier(gl_toolbox.repo, gl_toolbox.search, gitlab_enabled=True)
    report = verifier.verify("!1 ile geldi; !99 diye bir şey yok.")
    assert report.valid_mrs == [1]
    assert report.invalid_mrs == [99]
