from __future__ import annotations

import subprocess
from datetime import date

from gitex.evals.fixture import FixtureRepo
from gitex.git.reader import GitRepo
from gitex.index.db import SCHEMA_VERSION, Database
from gitex.index.indexer import ensure_index, index_repo, is_stale, open_index
from gitex.index.search import FTSSearch, SearchQuery


def _git(repo: GitRepo, *args: str) -> None:
    subprocess.run(
        [
            "git",
            "-c",
            "user.name=Test",
            "-c",
            "user.email=test@example.com",
            "-c",
            "commit.gpgsign=false",
            *args,
        ],
        cwd=repo.root,
        check=True,
        capture_output=True,
    )


def test_schema_version(indexed_db: Database) -> None:
    assert indexed_db.schema_version() == SCHEMA_VERSION


def test_full_index(indexed_db: Database, fixture_repo: FixtureRepo) -> None:
    assert indexed_db.count("commits") == len(fixture_repo.shas)
    refs = {r["name"] for r in indexed_db.conn.execute("SELECT name FROM refs")}
    assert {"main", "feature/refund", "v1.0", "v1.1"} <= refs
    renamed = indexed_db.conn.execute(
        "SELECT path, old_path, status FROM file_changes WHERE sha = ?",
        (fixture_repo.sha("rename"),),
    ).fetchone()
    assert tuple(renamed) == ("app/helpers.py", "app/utils.py", "R")


def test_incremental_index_adds_only_new(repo: GitRepo, indexed_db: Database) -> None:
    assert not is_stale(repo, indexed_db)
    again = index_repo(repo, indexed_db)
    assert (again.added, again.removed) == (0, 0)

    (repo.root / "NEW.md").write_text("yeni\n", encoding="utf-8")
    _git(repo, "add", "NEW.md")
    _git(repo, "commit", "-q", "-m", "Yeni belge eklendi")
    assert is_stale(repo, indexed_db)
    stats = index_repo(repo, indexed_db)
    assert (stats.added, stats.removed) == (1, 0)
    assert not is_stale(repo, indexed_db)


def test_rewritten_history_is_cleaned(
    repo: GitRepo, indexed_db: Database, fixture_repo: FixtureRepo
) -> None:
    # Son commit'i at (force-push / rebase simülasyonu); tag'i de kaldır ki erişilmez olsun.
    _git(repo, "tag", "-d", "v1.1")
    _git(repo, "reset", "-q", "--hard", "HEAD~1")
    _git(repo, "reflog", "expire", "--expire=now", "--all")
    stats = index_repo(repo, indexed_db)
    assert stats.removed == 1
    gone = fixture_repo.sha("settings")
    assert (
        indexed_db.conn.execute("SELECT 1 FROM commits WHERE sha = ?", (gone,)).fetchone() is None
    )
    assert (
        indexed_db.conn.execute("SELECT 1 FROM file_changes WHERE sha = ?", (gone,)).fetchone()
        is None
    )
    search = FTSSearch(indexed_db)
    assert search.search_commits(SearchQuery(text="Ayarlar dosyası")) == []


def test_rebuild(repo: GitRepo, indexed_db: Database, fixture_repo: FixtureRepo) -> None:
    indexed_db.close()
    with open_index(repo, rebuild=True) as db:
        assert db.count("commits") == 0
        stats = index_repo(repo, db)
        assert stats.added == len(fixture_repo.shas)


def test_ensure_index_creates_when_missing(repo: GitRepo, fixture_repo: FixtureRepo) -> None:
    db, stats = ensure_index(repo)
    try:
        assert stats is not None
        assert stats.added == len(fixture_repo.shas)
        _db2, stats2 = ensure_index(repo)
        _db2.close()
        assert stats2 is None
    finally:
        db.close()


# ---------------------------------------------------------------------- arama


def test_fts_turkish_diacritics(indexed_db: Database, fixture_repo: FixtureRepo) -> None:
    search = FTSSearch(indexed_db)
    for q in ("ödeme", "odeme", "ÖDEME", "Ödemeler"):
        hits = search.search_commits(SearchQuery(text=q))
        assert fixture_repo.sha("payment") in [h.sha for h in hits], q


def test_fts_dotless_i(indexed_db: Database, fixture_repo: FixtureRepo) -> None:
    search = FTSSearch(indexed_db)
    for q in ("kullanıcı silme", "kullanici silme", "KULLANICI"):
        hits = search.search_commits(SearchQuery(text=q))
        assert fixture_repo.sha("soft_delete") in [h.sha for h in hits], q


def test_fts_searches_body(indexed_db: Database, fixture_repo: FixtureRepo) -> None:
    hits = FTSSearch(indexed_db).search_commits(SearchQuery(text="brute-force"))
    assert hits[0].sha == fixture_repo.sha("rate_limit")


def test_search_filters(indexed_db: Database, fixture_repo: FixtureRepo) -> None:
    search = FTSSearch(indexed_db)
    by_path = search.search_commits(SearchQuery(path="auth/login.py"))
    assert {h.sha for h in by_path} == {
        fixture_repo.sha("login"),
        fixture_repo.sha("rate_limit"),
        fixture_repo.sha("rate_limit_10"),
    }
    by_dir = search.search_commits(SearchQuery(path="payment"))
    assert fixture_repo.sha("retry") in {h.sha for h in by_dir}
    by_author = search.search_commits(SearchQuery(author="ayse"))
    assert by_author
    assert all(h.author_name == "Ayşe Yılmaz" for h in by_author)
    ranged = search.search_commits(
        SearchQuery(text="rate limit", since=date(2026, 3, 1), until=date(2026, 3, 31))
    )
    assert [h.sha for h in ranged] == [fixture_repo.sha("rate_limit_10")]
    old_path = search.search_commits(SearchQuery(path="app/utils.py"))
    assert fixture_repo.sha("rename") in {h.sha for h in old_path}


def test_search_without_text_orders_by_date(indexed_db: Database) -> None:
    hits = FTSSearch(indexed_db).search_commits(SearchQuery(limit=3))
    dates = [h.author_date for h in hits]
    assert dates == sorted(dates, reverse=True)


def test_search_handles_fts_syntax(indexed_db: Database) -> None:
    # Kullanıcı girdisindeki FTS operatörleri sözdizimi hatasına yol açmamalı.
    search = FTSSearch(indexed_db)
    for q in ('"', "AND OR NOT", "login*", "(x", "a:b"):
        search.search_commits(SearchQuery(text=q))


def test_commit_exists(indexed_db: Database, fixture_repo: FixtureRepo) -> None:
    search = FTSSearch(indexed_db)
    sha = fixture_repo.sha("retry")
    assert search.commit_exists(sha[:7]) == sha
    assert search.commit_exists("0000000") is None
