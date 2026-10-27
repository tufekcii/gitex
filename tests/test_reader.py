from __future__ import annotations

from pathlib import Path

import pytest

from gitex.errors import NotAGitRepoError
from gitex.evals.fixture import FixtureRepo, empty_repo
from gitex.git.reader import GitRepo, parse_hunks


def test_not_a_repo(tmp_path: Path) -> None:
    with pytest.raises(NotAGitRepoError):
        GitRepo(tmp_path)


def test_empty_repo(tmp_path: Path) -> None:
    repo = GitRepo(empty_repo(tmp_path / "empty"))
    assert repo.head() is None
    assert repo.is_empty()
    assert repo.list_commits() == []
    assert repo.all_commit_shas() == []
    assert repo.pickaxe("x") == []
    assert repo.file_history("a.py") == []
    assert repo.list_paths("*") == []


def test_list_commits_metadata(repo: GitRepo, fixture_repo: FixtureRepo) -> None:
    commits = repo.list_commits(all_refs=True)
    assert len(commits) == len(fixture_repo.shas)
    by_sha = {c.sha: c for c in commits}
    login = by_sha[fixture_repo.sha("rate_limit")]
    assert login.author_name == "Mehmet Demir"
    assert login.author_email == "mehmet@example.com"
    assert login.author_date.date().isoformat() == "2026-01-20"
    assert login.subject == "Login'e rate limit eklendi"
    assert "Brute-force" in login.body
    assert [f.path for f in login.files] == ["auth/login.py"]
    assert login.files[0].additions == 13
    assert login.files[0].deletions == 1


def test_turkish_author_and_subject(repo: GitRepo, fixture_repo: FixtureRepo) -> None:
    commit = repo.get_commit(fixture_repo.sha("payment"))
    assert commit is not None
    assert commit.author_name == "Ayşe Yılmaz"
    assert commit.subject == "Ödeme servisi eklendi"


def test_rename_detected(repo: GitRepo, fixture_repo: FixtureRepo) -> None:
    commit = repo.get_commit(fixture_repo.sha("rename"))
    assert commit is not None
    (change,) = commit.files
    assert change.status == "R"
    assert change.path == "app/helpers.py"
    assert change.old_path == "app/utils.py"


def test_file_history_follows_rename(repo: GitRepo, fixture_repo: FixtureRepo) -> None:
    shas = [c.sha for c in repo.file_history("app/helpers.py")]
    assert shas == [fixture_repo.sha("rename"), fixture_repo.sha("init")]


def test_deleted_file(repo: GitRepo, fixture_repo: FixtureRepo) -> None:
    commit = repo.get_commit(fixture_repo.sha("legacy_delete"))
    assert commit is not None
    assert [(f.status, f.path) for f in commit.files] == [("D", "legacy/old.py")]
    assert repo.path_exists_in_history("legacy/old.py")
    assert "legacy/old.py" not in repo.list_paths("*")


def test_merge_commit(repo: GitRepo, fixture_repo: FixtureRepo) -> None:
    merge = repo.get_commit(fixture_repo.sha("merge_refund"))
    assert merge is not None
    assert merge.is_merge
    assert len(merge.parents) == 2
    # Merge diff'i ilk parent'a göre: refund'ın getirdiği değişiklik.
    assert [f.path for f in merge.files] == ["payment/service.py"]


def test_pickaxe_added_and_removed(repo: GitRepo, fixture_repo: FixtureRepo) -> None:
    hits = repo.pickaxe("debug_dump")
    assert [(h.commit.sha, h.kind) for h in hits] == [
        (fixture_repo.sha("debug_remove"), "kaldırıldı"),
        (fixture_repo.sha("debug_add"), "eklendi"),
    ]


def test_pickaxe_regex(repo: GitRepo, fixture_repo: FixtureRepo) -> None:
    hits = repo.pickaxe(r"RATE_LIMIT = [0-9]+", regex=True)
    assert [h.commit.sha for h in hits] == [
        fixture_repo.sha("rate_limit_10"),
        fixture_repo.sha("rate_limit"),
    ]
    assert hits[0].kind == "değişti"


def test_pickaxe_with_path(repo: GitRepo, fixture_repo: FixtureRepo) -> None:
    assert repo.pickaxe("def refund", path="auth/login.py") == []
    hits = repo.pickaxe("def refund", path="payment/service.py", all_refs=True)
    assert fixture_repo.sha("refund") in [h.commit.sha for h in hits]


def test_line_history(repo: GitRepo, fixture_repo: FixtureRepo) -> None:
    entries = repo.line_history("auth/login.py", 5, 5)
    assert [e.commit.sha for e in entries] == [
        fixture_repo.sha("rate_limit_10"),
        fixture_repo.sha("rate_limit"),
    ]
    assert "+RATE_LIMIT = 10" in entries[0].diff
    hunks = parse_hunks(entries[0].diff)
    assert hunks
    assert hunks[0].new_start == 5


def test_blame(repo: GitRepo, fixture_repo: FixtureRepo) -> None:
    lines = repo.blame("auth/login.py", 5, 5)
    assert len(lines) == 1
    assert lines[0].sha == fixture_repo.sha("rate_limit_10")
    assert lines[0].author_name == "Mehmet Demir"
    assert lines[0].content.startswith("RATE_LIMIT = 10")
    assert lines[0].summary.startswith("Rate limit 5'ten 10'a")


def test_refs_containing(repo: GitRepo, fixture_repo: FixtureRepo) -> None:
    assert repo.tags_containing(fixture_repo.sha("rate_limit")) == ["v1.0", "v1.1"]
    assert repo.tags_containing(fixture_repo.sha("retry")) == ["v1.1"]
    assert set(repo.branches_containing(fixture_repo.sha("refund"))) == {"feature/refund", "main"}


def test_diff_excludes_and_truncates(repo: GitRepo, fixture_repo: FixtureRepo) -> None:
    diff = repo.diff(fixture_repo.sha("settings"), exclude_paths=["*.env"])
    assert diff.excluded_paths == ("config/prod.env",)
    assert "config/settings.py" in diff.text
    assert "SECRET_TOKEN" not in diff.text
    small = repo.diff(fixture_repo.sha("retry"), max_chars=50)
    assert small.truncated
    assert len(small.text) == 50


def test_list_paths(repo: GitRepo) -> None:
    assert repo.list_paths("payment/**") == ["payment/__init__.py", "payment/service.py"]
    assert repo.list_paths("LOGIN") == ["auth/login.py"]
    assert "config/prod.env" in repo.list_paths("*.env")


def test_resolve(repo: GitRepo, fixture_repo: FixtureRepo) -> None:
    sha = fixture_repo.sha("payment")
    assert repo.resolve(sha[:7]) == sha
    assert repo.resolve("deadbee") is None
    assert repo.resolve("--all") is None
