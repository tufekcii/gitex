"""Git verisi için değişmez veri modelleri."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime


@dataclass(frozen=True, slots=True)
class FileChange:
    """Bir commit'te değişen tek dosya.

    `status`: A (eklendi), M (değişti), D (silindi), R (yeniden adlandırıldı), C (kopyalandı), T.
    `additions`/`deletions` ikili dosyalarda None olur.
    """

    path: str
    status: str
    old_path: str | None = None
    additions: int | None = None
    deletions: int | None = None


@dataclass(frozen=True, slots=True)
class Commit:
    sha: str
    parents: tuple[str, ...]
    author_name: str
    author_email: str
    author_date: datetime
    committer_name: str
    committer_email: str
    committer_date: datetime
    subject: str
    body: str = ""
    files: tuple[FileChange, ...] = field(default_factory=tuple)

    @property
    def short_sha(self) -> str:
        return self.sha[:7]

    @property
    def is_merge(self) -> bool:
        return len(self.parents) > 1

    @property
    def message(self) -> str:
        return f"{self.subject}\n\n{self.body}".strip() if self.body else self.subject


@dataclass(frozen=True, slots=True)
class Hunk:
    """Unified diff içindeki tek bir parça (`@@ -a,b +c,d @@`)."""

    old_start: int
    old_lines: int
    new_start: int
    new_lines: int
    header: str
    lines: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class BlameLine:
    sha: str
    line_no: int
    orig_line_no: int
    orig_path: str
    author_name: str
    author_email: str
    author_date: datetime
    summary: str
    content: str


@dataclass(frozen=True, slots=True)
class LineHistoryEntry:
    """`git log -L` çıktısındaki bir adım: commit + o commit'teki ilgili diff."""

    commit: Commit
    diff: str


@dataclass(frozen=True, slots=True)
class PickaxeHit:
    """Pickaxe sonucu; terimin o commit'te kaç satırda eklendiği/kaldırıldığı."""

    commit: Commit
    added: int
    removed: int

    @property
    def kind(self) -> str:
        if self.added and not self.removed:
            return "eklendi"
        if self.removed and not self.added:
            return "kaldırıldı"
        return "değişti"


@dataclass(frozen=True, slots=True)
class Ref:
    name: str
    sha: str
    kind: str  # branch | remote | tag


@dataclass(frozen=True, slots=True)
class DiffText:
    text: str
    truncated: bool
    excluded_paths: tuple[str, ...] = ()
