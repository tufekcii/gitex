"""İndeks üzerinde arama.

`SearchBackend` arayüzü bilinçli olarak dar tutuldu: ileride `sqlite-vec` ile bir vektör
arka ucu eklenip `HybridSearch` FTS ve vektör sonuçlarını (ör. RRF ile) birleştirebilir;
çağıranlar yalnızca bu Protocol'e bağımlıdır.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, time
from typing import Protocol

from gitex.git.pathmatch import has_glob
from gitex.index.db import Database
from gitex.textnorm import fold, fts_query


@dataclass(frozen=True, slots=True)
class SearchQuery:
    text: str | None = None
    path: str | None = None
    author: str | None = None
    since: date | None = None
    until: date | None = None
    limit: int = 20


@dataclass(frozen=True, slots=True)
class CommitHit:
    sha: str
    subject: str
    author_name: str
    author_email: str
    author_date: str
    score: float
    files: tuple[str, ...] = ()
    is_merge: bool = False

    @property
    def short_sha(self) -> str:
        return self.sha[:7]


@dataclass(frozen=True, slots=True)
class MRHit:
    iid: int
    title: str
    state: str
    author: str | None
    merged_at: str | None
    web_url: str | None
    score: float
    matched_in: tuple[str, ...] = ()  # "mr" | "note" | "issue"


@dataclass(frozen=True, slots=True)
class MRQuery:
    text: str | None = None
    state: str | None = None
    since: date | None = None
    until: date | None = None
    limit: int = 10


@dataclass
class MRDetail:
    iid: int
    title: str
    description: str
    state: str
    author: str | None
    source_branch: str | None
    target_branch: str | None
    web_url: str | None
    created_at: str | None
    merged_at: str | None
    merge_commit_sha: str | None
    squash_commit_sha: str | None
    commits: list[str] = field(default_factory=list)
    notes: list[dict[str, object]] = field(default_factory=list)
    issues: list[dict[str, object]] = field(default_factory=list)


class SearchBackend(Protocol):
    def search_commits(self, query: SearchQuery) -> list[CommitHit]: ...

    def search_mrs(self, query: MRQuery) -> list[MRHit]: ...


def _ts(d: date, end: bool = False) -> int:
    t = time.max if end else time.min
    return int(datetime.combine(d, t, tzinfo=UTC).timestamp())


def _iso(d: date, end: bool = False) -> str:
    return datetime.combine(d, time.max if end else time.min, tzinfo=UTC).isoformat()


class FTSSearch:
    """SQLite FTS5 tabanlı arama (bm25 sıralı)."""

    def __init__(self, db: Database) -> None:
        self.db = db

    # ------------------------------------------------------------------ commit

    def search_commits(self, query: SearchQuery) -> list[CommitHit]:
        where: list[str] = []
        params: list[object] = []
        match = fts_query(query.text) if query.text else None
        if match:
            base = (
                "SELECT c.*, bm25(commits_fts, 3.0, 1.0) AS score FROM commits_fts "
                "JOIN commits c ON c.rowid = commits_fts.rowid"
            )
            where.append("commits_fts MATCH ?")
            params.append(match)
            order = "score ASC, c.author_ts DESC"
        else:
            base = "SELECT c.*, 0.0 AS score FROM commits c"
            order = "c.author_ts DESC"
        if query.path:
            path = query.path.strip("/")
            if has_glob(path):
                where.append(
                    "EXISTS (SELECT 1 FROM file_changes fc WHERE fc.sha = c.sha "
                    "AND (fc.path GLOB ? OR fc.old_path GLOB ?))"
                )
                params += [path, path]
            else:
                where.append(
                    "EXISTS (SELECT 1 FROM file_changes fc WHERE fc.sha = c.sha AND "
                    "(fc.path = ? OR fc.old_path = ? OR fc.path LIKE ? ESCAPE '\\'))"
                )
                escaped = path.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
                params += [path, path, f"{escaped}/%"]
        if query.author:
            where.append(
                "(instr(tr_fold(c.author_name), ?) > 0 OR instr(tr_fold(c.author_email), ?) > 0)"
            )
            params += [fold(query.author), fold(query.author)]
        if query.since:
            where.append("c.author_ts >= ?")
            params.append(_ts(query.since))
        if query.until:
            where.append("c.author_ts <= ?")
            params.append(_ts(query.until, end=True))
        sql = (
            base + (" WHERE " + " AND ".join(where) if where else "") + f" ORDER BY {order} LIMIT ?"
        )
        params.append(query.limit)
        rows = self.db.conn.execute(sql, params).fetchall()
        hits: list[CommitHit] = []
        for row in rows:
            files = tuple(
                r[0]
                for r in self.db.conn.execute(
                    "SELECT path FROM file_changes WHERE sha = ? LIMIT 20", (row["sha"],)
                )
            )
            hits.append(
                CommitHit(
                    sha=row["sha"],
                    subject=row["subject"],
                    author_name=row["author_name"],
                    author_email=row["author_email"],
                    author_date=row["author_date"],
                    score=-float(row["score"]),
                    files=files,
                    is_merge=bool(row["is_merge"]),
                )
            )
        return hits

    # ------------------------------------------------------------------ MR / issue

    def search_mrs(self, query: MRQuery) -> list[MRHit]:
        scores: dict[int, float] = {}
        matched: dict[int, set[str]] = {}
        match = fts_query(query.text) if query.text else None
        conn = self.db.conn
        if match:
            sources = (
                (
                    "mr",
                    "SELECT rowid AS iid, bm25(mrs_fts, 3.0, 1.0) AS s FROM mrs_fts "
                    "WHERE mrs_fts MATCH ?",
                ),
                (
                    "note",
                    "SELECT n.mr_iid AS iid, bm25(mr_notes_fts) AS s FROM mr_notes_fts "
                    "JOIN mr_notes n ON n.id = mr_notes_fts.rowid WHERE mr_notes_fts MATCH ?",
                ),
                (
                    "issue",
                    "SELECT mi.mr_iid AS iid, bm25(issues_fts, 3.0, 1.0) AS s FROM issues_fts "
                    "JOIN mr_issues mi ON mi.issue_iid = issues_fts.rowid WHERE issues_fts MATCH ?",
                ),
            )
            weights = {"mr": 1.0, "note": 0.6, "issue": 0.8}
            for name, sql in sources:
                for row in conn.execute(sql, (match,)):
                    iid = int(row["iid"])
                    scores[iid] = scores.get(iid, 0.0) + weights[name] * -float(row["s"])
                    matched.setdefault(iid, set()).add(name)
            if not scores:
                return []
        where: list[str] = []
        params: list[object] = []
        if scores:
            where.append(f"iid IN ({','.join('?' * len(scores))})")
            params += list(scores)
        if query.state:
            where.append("state = ?")
            params.append(query.state)
        if query.since:
            where.append("COALESCE(merged_at, created_at) >= ?")
            params.append(_iso(query.since))
        if query.until:
            where.append("COALESCE(merged_at, created_at) <= ?")
            params.append(_iso(query.until, end=True))
        sql = "SELECT * FROM merge_requests" + (" WHERE " + " AND ".join(where) if where else "")
        rows = conn.execute(sql, params).fetchall()
        hits = [
            MRHit(
                iid=int(r["iid"]),
                title=r["title"],
                state=r["state"],
                author=r["author"],
                merged_at=r["merged_at"],
                web_url=r["web_url"],
                score=scores.get(int(r["iid"]), 0.0),
                matched_in=tuple(sorted(matched.get(int(r["iid"]), set()))),
            )
            for r in rows
        ]
        if scores:
            hits.sort(key=lambda h: -h.score)
        else:
            hits.sort(key=lambda h: h.merged_at or "", reverse=True)
        return hits[: query.limit]

    def get_mr(self, iid: int) -> MRDetail | None:
        conn = self.db.conn
        r = conn.execute("SELECT * FROM merge_requests WHERE iid = ?", (iid,)).fetchone()
        if r is None:
            return None
        detail = MRDetail(
            iid=int(r["iid"]),
            title=r["title"],
            description=r["description"],
            state=r["state"],
            author=r["author"],
            source_branch=r["source_branch"],
            target_branch=r["target_branch"],
            web_url=r["web_url"],
            created_at=r["created_at"],
            merged_at=r["merged_at"],
            merge_commit_sha=r["merge_commit_sha"],
            squash_commit_sha=r["squash_commit_sha"],
        )
        detail.commits = [
            row[0] for row in conn.execute("SELECT sha FROM mr_commits WHERE mr_iid = ?", (iid,))
        ]
        detail.notes = [
            dict(row)
            for row in conn.execute(
                "SELECT author, body, created_at, file_path, line FROM mr_notes "
                "WHERE mr_iid = ? ORDER BY created_at",
                (iid,),
            )
        ]
        for row in conn.execute(
            "SELECT i.*, mi.relation FROM mr_issues mi JOIN issues i ON i.iid = mi.issue_iid "
            "WHERE mi.mr_iid = ?",
            (iid,),
        ):
            issue = dict(row)
            issue["labels"] = json.loads(issue.get("labels") or "[]")
            detail.issues.append(issue)
        return detail

    def mrs_for_commit(self, sha: str) -> list[MRHit]:
        """Bir commit'i içeren MR'lar: MR commit'i, merge commit'i ya da squash commit'i olarak."""
        rows = self.db.conn.execute(
            """SELECT DISTINCT m.* FROM merge_requests m
               LEFT JOIN mr_commits mc ON mc.mr_iid = m.iid
               WHERE mc.sha = ? OR m.merge_commit_sha = ? OR m.squash_commit_sha = ?
               ORDER BY m.merged_at DESC""",
            (sha, sha, sha),
        ).fetchall()
        return [
            MRHit(
                iid=int(r["iid"]),
                title=r["title"],
                state=r["state"],
                author=r["author"],
                merged_at=r["merged_at"],
                web_url=r["web_url"],
                score=0.0,
            )
            for r in rows
        ]

    def commit_exists(self, sha_prefix: str) -> str | None:
        """Önek tek bir commit'e karşılık geliyorsa tam SHA'yı döner."""
        prefix = sha_prefix.lower()
        rows = self.db.conn.execute(
            "SELECT sha FROM commits WHERE sha >= ? AND sha < ? LIMIT 2", (prefix, prefix + "g")
        ).fetchall()
        return str(rows[0][0]) if len(rows) == 1 else None

    def mr_exists(self, iid: int) -> bool:
        row = self.db.conn.execute("SELECT 1 FROM merge_requests WHERE iid = ?", (iid,)).fetchone()
        return row is not None
