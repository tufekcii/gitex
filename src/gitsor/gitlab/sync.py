"""GitLab MR / not / issue verisinin indekse artımlı senkronizasyonu."""

from __future__ import annotations

import json
import time
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime

from gitsor.gitlab.client import WANTED_STATES, GitLabClient, MRData
from gitsor.index.db import Database
from gitsor.textnorm import fold

SyncProgressFn = Callable[[int], None]


@dataclass(frozen=True, slots=True)
class SyncStats:
    synced: int
    removed: int
    notes: int
    issues: int
    elapsed: float
    full: bool


def _clear_mr(db: Database, iid: int) -> None:
    conn = db.conn
    conn.execute(
        "DELETE FROM mr_notes_fts WHERE rowid IN (SELECT id FROM mr_notes WHERE mr_iid = ?)", (iid,)
    )
    conn.execute("DELETE FROM mrs_fts WHERE rowid = ?", (iid,))
    conn.execute(
        "DELETE FROM merge_requests WHERE iid = ?", (iid,)
    )  # cascade: commits/notes/issues bağı


def _clear_all(db: Database) -> None:
    for table in (
        "mr_notes_fts",
        "mrs_fts",
        "issues_fts",
        "mr_issues",
        "mr_notes",
        "mr_commits",
        "issues",
    ):
        db.conn.execute(f"DELETE FROM {table}")
    db.conn.execute("DELETE FROM merge_requests")


def write_mr(db: Database, mr: MRData) -> None:
    conn = db.conn
    _clear_mr(db, mr.iid)
    conn.execute(
        """INSERT INTO merge_requests(iid, title, description, state, author, source_branch,
               target_branch, web_url, created_at, updated_at, merged_at, merge_commit_sha,
               squash_commit_sha)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (
            mr.iid,
            mr.title,
            mr.description,
            mr.state,
            mr.author,
            mr.source_branch,
            mr.target_branch,
            mr.web_url,
            mr.created_at,
            mr.updated_at,
            mr.merged_at,
            mr.merge_commit_sha,
            mr.squash_commit_sha,
        ),
    )
    conn.execute(
        "INSERT INTO mrs_fts(rowid, title, description) VALUES (?, ?, ?)",
        (mr.iid, fold(mr.title), fold(mr.description)),
    )
    conn.executemany(
        "INSERT OR IGNORE INTO mr_commits(mr_iid, sha) VALUES (?, ?)",
        [(mr.iid, sha) for sha in mr.commits],
    )
    for note in mr.notes:
        conn.execute("DELETE FROM mr_notes_fts WHERE rowid = ?", (note["id"],))
        conn.execute(
            """INSERT OR REPLACE INTO mr_notes(id, mr_iid, author, body, created_at, file_path, line)
               VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (
                note["id"],
                mr.iid,
                note["author"],
                note["body"],
                note["created_at"],
                note["file_path"],
                note["line"],
            ),
        )
        conn.execute(
            "INSERT INTO mr_notes_fts(rowid, body) VALUES (?, ?)", (note["id"], fold(note["body"]))
        )
    for issue in mr.issues:
        conn.execute(
            """INSERT OR REPLACE INTO issues(iid, title, description, state, labels, author, web_url,
                   created_at, updated_at, closed_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                issue["iid"],
                issue["title"],
                issue["description"],
                issue["state"],
                json.dumps(issue["labels"], ensure_ascii=False),
                issue["author"],
                issue["web_url"],
                issue["created_at"],
                issue["updated_at"],
                issue["closed_at"],
            ),
        )
        conn.execute("DELETE FROM issues_fts WHERE rowid = ?", (issue["iid"],))
        conn.execute(
            "INSERT INTO issues_fts(rowid, title, description) VALUES (?, ?, ?)",
            (issue["iid"], fold(issue["title"]), fold(issue["description"])),
        )
        conn.execute(
            "INSERT OR REPLACE INTO mr_issues(mr_iid, issue_iid, relation) VALUES (?, ?, ?)",
            (mr.iid, issue["iid"], issue["relation"]),
        )


def sync_gitlab(
    client: GitLabClient,
    db: Database,
    *,
    full: bool = False,
    progress: SyncProgressFn | None = None,
    now: Callable[[], datetime] = lambda: datetime.now(UTC),
) -> SyncStats:
    """`updated_after` imleciyle artımlı senkron. Proje değiştiyse ya da `full` ise sıfırdan."""
    start = time.monotonic()
    project = str(client.cfg.project)
    if db.get_meta("gitlab_project") not in (None, project):
        full = True
    cursor = None if full else db.get_meta("gitlab_last_sync")
    # İmleç, senkron başlamadan alınır: senkron sırasında güncellenen MR'lar bir sonraki turda gelir.
    started_at = now().isoformat(timespec="seconds")
    if full:
        with db.transaction():
            _clear_all(db)

    synced = removed = notes = issues = 0
    for raw in client.iter_merge_requests(updated_after=cursor):
        iid = int(raw["iid"])
        if raw.get("state") not in WANTED_STATES:
            if db.conn.execute("SELECT 1 FROM merge_requests WHERE iid = ?", (iid,)).fetchone():
                with db.transaction():
                    _clear_mr(db, iid)
                removed += 1
            continue
        mr = client.fetch_details(raw)
        with db.transaction():
            write_mr(db, mr)
        synced += 1
        notes += len(mr.notes)
        issues += len(mr.issues)
        if progress:
            progress(synced)

    with db.transaction():
        db.set_meta("gitlab_last_sync", started_at)
        db.set_meta("gitlab_project", project)
    return SyncStats(synced, removed, notes, issues, time.monotonic() - start, full)
