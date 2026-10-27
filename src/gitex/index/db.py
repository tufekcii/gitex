"""SQLite indeks şeması, migration ve FTS5 tabloları."""

from __future__ import annotations

import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

from gitex.textnorm import fold

SCHEMA_VERSION = 1

# FTS5 tabloları normal (içerik saklayan) tablolardır; metin `fold()` ile katlanmış
# hâlde yazılır. Böylece `ı`/`i`, `İ`/`i` eşleşmesi de sağlanır (unicode61 bunu yapmaz).
_TOKENIZER = "unicode61 remove_diacritics 2"

_SCHEMA_V1 = f"""
CREATE TABLE IF NOT EXISTS meta (
    key TEXT PRIMARY KEY,
    value TEXT
);

CREATE TABLE IF NOT EXISTS commits (
    sha TEXT PRIMARY KEY,
    parents TEXT NOT NULL,
    author_name TEXT NOT NULL,
    author_email TEXT NOT NULL,
    author_date TEXT NOT NULL,
    author_ts INTEGER NOT NULL,
    committer_name TEXT NOT NULL,
    committer_email TEXT NOT NULL,
    committer_date TEXT NOT NULL,
    committer_ts INTEGER NOT NULL,
    subject TEXT NOT NULL,
    body TEXT NOT NULL,
    is_merge INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS commits_author_ts ON commits(author_ts);

CREATE TABLE IF NOT EXISTS file_changes (
    sha TEXT NOT NULL REFERENCES commits(sha) ON DELETE CASCADE,
    path TEXT NOT NULL,
    old_path TEXT,
    status TEXT NOT NULL,
    additions INTEGER,
    deletions INTEGER
);
CREATE INDEX IF NOT EXISTS file_changes_sha ON file_changes(sha);
CREATE INDEX IF NOT EXISTS file_changes_path ON file_changes(path);
CREATE INDEX IF NOT EXISTS file_changes_old_path ON file_changes(old_path);

CREATE TABLE IF NOT EXISTS refs (
    name TEXT NOT NULL,
    kind TEXT NOT NULL,
    sha TEXT NOT NULL,
    PRIMARY KEY (kind, name)
);

CREATE TABLE IF NOT EXISTS merge_requests (
    iid INTEGER PRIMARY KEY,
    title TEXT NOT NULL,
    description TEXT NOT NULL DEFAULT '',
    state TEXT NOT NULL,
    author TEXT,
    source_branch TEXT,
    target_branch TEXT,
    web_url TEXT,
    created_at TEXT,
    updated_at TEXT,
    merged_at TEXT,
    merge_commit_sha TEXT,
    squash_commit_sha TEXT
);
CREATE INDEX IF NOT EXISTS mr_merge_sha ON merge_requests(merge_commit_sha);
CREATE INDEX IF NOT EXISTS mr_squash_sha ON merge_requests(squash_commit_sha);

CREATE TABLE IF NOT EXISTS mr_commits (
    mr_iid INTEGER NOT NULL REFERENCES merge_requests(iid) ON DELETE CASCADE,
    sha TEXT NOT NULL,
    relation TEXT NOT NULL DEFAULT 'commit',
    PRIMARY KEY (mr_iid, sha)
);
CREATE INDEX IF NOT EXISTS mr_commits_sha ON mr_commits(sha);

CREATE TABLE IF NOT EXISTS mr_notes (
    id INTEGER PRIMARY KEY,
    mr_iid INTEGER NOT NULL REFERENCES merge_requests(iid) ON DELETE CASCADE,
    author TEXT,
    body TEXT NOT NULL,
    created_at TEXT,
    file_path TEXT,
    line INTEGER
);
CREATE INDEX IF NOT EXISTS mr_notes_mr ON mr_notes(mr_iid);

CREATE TABLE IF NOT EXISTS issues (
    iid INTEGER PRIMARY KEY,
    title TEXT NOT NULL,
    description TEXT NOT NULL DEFAULT '',
    state TEXT,
    labels TEXT NOT NULL DEFAULT '[]',
    author TEXT,
    web_url TEXT,
    created_at TEXT,
    updated_at TEXT,
    closed_at TEXT
);

CREATE TABLE IF NOT EXISTS mr_issues (
    mr_iid INTEGER NOT NULL REFERENCES merge_requests(iid) ON DELETE CASCADE,
    issue_iid INTEGER NOT NULL,
    relation TEXT NOT NULL,
    PRIMARY KEY (mr_iid, issue_iid)
);

CREATE VIRTUAL TABLE IF NOT EXISTS commits_fts USING fts5(subject, body, tokenize='{_TOKENIZER}');
CREATE VIRTUAL TABLE IF NOT EXISTS mrs_fts USING fts5(title, description, tokenize='{_TOKENIZER}');
CREATE VIRTUAL TABLE IF NOT EXISTS mr_notes_fts USING fts5(body, tokenize='{_TOKENIZER}');
CREATE VIRTUAL TABLE IF NOT EXISTS issues_fts
    USING fts5(title, description, tokenize='{_TOKENIZER}');
"""

# Sürüm -> o sürüme geçiren SQL. Yeni şema değişikliği = yeni anahtar + SCHEMA_VERSION artışı.
MIGRATIONS: dict[int, str] = {1: _SCHEMA_V1}


class Database:
    """İndeks bağlantısı. `with db.transaction():` toplu yazımlar için kullanılır."""

    def __init__(self, path: Path | str) -> None:
        self.path = Path(path) if str(path) != ":memory:" else None
        if self.path is not None:
            self.path.parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(str(path), isolation_level=None)
        self.conn.row_factory = sqlite3.Row
        self.conn.execute("PRAGMA foreign_keys = ON")
        self.conn.execute("PRAGMA journal_mode = WAL")
        self.conn.execute("PRAGMA synchronous = NORMAL")
        self.conn.create_function("tr_fold", 1, _sql_fold, deterministic=True)
        self.migrate()

    def close(self) -> None:
        self.conn.close()

    def __enter__(self) -> Database:
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()

    @contextmanager
    def transaction(self) -> Iterator[sqlite3.Connection]:
        self.conn.execute("BEGIN")
        try:
            yield self.conn
        except BaseException:
            self.conn.execute("ROLLBACK")
            raise
        self.conn.execute("COMMIT")

    # ------------------------------------------------------------------ şema

    def schema_version(self) -> int:
        exists = self.conn.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name='meta'"
        ).fetchone()
        if not exists:
            return 0
        value = self.get_meta("schema_version")
        return int(value) if value else 0

    def migrate(self) -> None:
        current = self.schema_version()
        for version in sorted(MIGRATIONS):
            if version > current:
                with self.transaction() as conn:
                    for stmt in _split_sql(MIGRATIONS[version]):
                        conn.execute(stmt)
                    conn.execute(
                        "INSERT OR REPLACE INTO meta(key, value) VALUES ('schema_version', ?)",
                        (str(version),),
                    )

    # ------------------------------------------------------------------ meta

    def get_meta(self, key: str) -> str | None:
        row = self.conn.execute("SELECT value FROM meta WHERE key = ?", (key,)).fetchone()
        return None if row is None else str(row[0])

    def set_meta(self, key: str, value: str) -> None:
        self.conn.execute("INSERT OR REPLACE INTO meta(key, value) VALUES (?, ?)", (key, value))

    def count(self, table: str) -> int:
        if table not in _COUNTABLE:
            raise ValueError(table)
        return int(self.conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0])


_COUNTABLE = {
    "commits",
    "file_changes",
    "refs",
    "merge_requests",
    "mr_notes",
    "issues",
    "mr_commits",
}


def _sql_fold(value: object) -> str | None:
    return None if value is None else fold(str(value))


def _split_sql(script: str) -> list[str]:
    return [s.strip() for s in script.split(";\n") if s.strip()]
