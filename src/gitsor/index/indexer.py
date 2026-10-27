"""Git verisini indekse yazar (artımlı, force-push/rebase'e dayanıklı)."""

from __future__ import annotations

import time
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from gitsor.config import index_path
from gitsor.git.models import Commit
from gitsor.git.reader import GitRepo
from gitsor.index.db import Database
from gitsor.textnorm import fold

BATCH_SIZE = 2000

ProgressFn = Callable[[int, int], None]


@dataclass(frozen=True, slots=True)
class IndexStats:
    added: int
    removed: int
    total: int
    elapsed: float
    rebuilt: bool = False


def open_index(repo: GitRepo, *, rebuild: bool = False) -> Database:
    path = index_path(repo.root)
    if rebuild:
        for suffix in ("", "-wal", "-shm"):
            Path(f"{path}{suffix}").unlink(missing_ok=True)
    return Database(path)


def _chunks(items: list[str], size: int) -> Iterable[list[str]]:
    for i in range(0, len(items), size):
        yield items[i : i + size]


def _insert_commits(db: Database, commits: list[Commit]) -> None:
    conn = db.conn
    conn.executemany(
        """INSERT OR REPLACE INTO commits(sha, parents, author_name, author_email, author_date,
               author_ts, committer_name, committer_email, committer_date, committer_ts,
               subject, body, is_merge)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        [
            (
                c.sha,
                " ".join(c.parents),
                c.author_name,
                c.author_email,
                c.author_date.isoformat(),
                int(c.author_date.timestamp()),
                c.committer_name,
                c.committer_email,
                c.committer_date.isoformat(),
                int(c.committer_date.timestamp()),
                c.subject,
                c.body,
                int(c.is_merge),
            )
            for c in commits
        ],
    )
    conn.executemany(
        """INSERT INTO file_changes(sha, path, old_path, status, additions, deletions)
           VALUES (?, ?, ?, ?, ?, ?)""",
        [
            (c.sha, f.path, f.old_path, f.status, f.additions, f.deletions)
            for c in commits
            for f in c.files
        ],
    )
    rows = conn.execute(
        f"SELECT rowid, sha FROM commits WHERE sha IN ({','.join('?' * len(commits))})",
        [c.sha for c in commits],
    ).fetchall()
    rowids = {r["sha"]: r["rowid"] for r in rows}
    conn.executemany(
        "INSERT OR REPLACE INTO commits_fts(rowid, subject, body) VALUES (?, ?, ?)",
        [(rowids[c.sha], fold(c.subject), fold(c.body)) for c in commits],
    )


def _delete_commits(db: Database, shas: list[str]) -> None:
    conn = db.conn
    for chunk in _chunks(shas, 500):
        marks = ",".join("?" * len(chunk))
        conn.execute(
            "DELETE FROM commits_fts WHERE rowid IN "
            f"(SELECT rowid FROM commits WHERE sha IN ({marks}))",
            chunk,
        )
        conn.execute(f"DELETE FROM commits WHERE sha IN ({marks})", chunk)


def _write_refs(db: Database, repo: GitRepo) -> None:
    db.conn.execute("DELETE FROM refs")
    db.conn.executemany(
        "INSERT INTO refs(name, kind, sha) VALUES (?, ?, ?)",
        [(r.name, r.kind, r.sha) for r in repo.list_refs()],
    )


def index_repo(
    repo: GitRepo,
    db: Database,
    *,
    progress: ProgressFn | None = None,
    batch_size: int = BATCH_SIZE,
) -> IndexStats:
    """Erişilebilir tüm commit'leri indeksle; artık erişilemeyenleri (rebase/force-push) temizle."""
    start = time.monotonic()
    current = repo.all_commit_shas()
    current_set = set(current)
    known = {row[0] for row in db.conn.execute("SELECT sha FROM commits")}
    new = [sha for sha in current if sha not in known]
    vanished = sorted(known - current_set)

    if vanished:
        with db.transaction():
            _delete_commits(db, vanished)

    done = 0
    for chunk in _chunks(new, batch_size):
        commits = repo.commits_by_sha(chunk)
        with db.transaction():
            _insert_commits(db, commits)
        done += len(chunk)
        if progress:
            progress(done, len(new))

    with db.transaction():
        _write_refs(db, repo)
        db.set_meta("last_indexed_head", repo.head() or "")
        db.set_meta("refs_fingerprint", repo.refs_fingerprint())
        db.set_meta("last_indexed_at", datetime.now(UTC).isoformat(timespec="seconds"))
    return IndexStats(
        added=len(new),
        removed=len(vanished),
        total=db.count("commits"),
        elapsed=time.monotonic() - start,
    )


def is_stale(repo: GitRepo, db: Database) -> bool:
    return db.get_meta("refs_fingerprint") != repo.refs_fingerprint()


def ensure_index(
    repo: GitRepo, *, progress: ProgressFn | None = None
) -> tuple[Database, IndexStats | None]:
    """İndeksi açar; yoksa ya da eskiyse artımlı indeksler."""
    db = open_index(repo)
    if is_stale(repo, db):
        return db, index_repo(repo, db, progress=progress)
    return db, None
