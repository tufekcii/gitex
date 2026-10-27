"""Cevaptaki SHA ve MR referanslarını çıkarır ve indekste/git'te var olduklarını doğrular."""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from gitex.git.reader import GitRepo
from gitex.i18n import t
from gitex.index.search import FTSSearch

# 7-40 hex karakter; en az bir rakam içermeli ("defaced", "facade" gibi kelimeleri dışlar).
_SHA_RE = re.compile(r"(?<![0-9a-zA-Z_/\-.])([0-9a-f]{7,40})(?![0-9a-zA-Z_\-])")
_MR_RE = re.compile(r"(?<![\w&])!(\d{1,7})\b")
_MR_URL_RE = re.compile(r"/-?/?merge_requests/(\d+)")


def warning_label() -> str:
    """Doğrulanamayan referansın yanına eklenen uyarı (arayüz dilinde)."""
    return t("⚠ doğrulanamadı", "⚠ unverified")


@dataclass
class CitationReport:
    valid_shas: dict[str, str] = field(default_factory=dict)  # yazıldığı hâli -> tam SHA
    invalid_shas: list[str] = field(default_factory=list)
    valid_mrs: list[int] = field(default_factory=list)
    invalid_mrs: list[int] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.invalid_shas and not self.invalid_mrs


def extract_shas(text: str) -> list[str]:
    out: list[str] = []
    for m in _SHA_RE.finditer(text):
        token = m.group(1)
        if any(c.isdigit() for c in token) and token not in out:
            out.append(token)
    return out


def extract_mrs(text: str) -> list[int]:
    out: list[int] = []
    for pattern in (_MR_RE, _MR_URL_RE):
        for m in pattern.finditer(text):
            iid = int(m.group(1))
            if iid not in out:
                out.append(iid)
    return out


class CitationVerifier:
    def __init__(self, repo: GitRepo, search: FTSSearch, *, gitlab_enabled: bool) -> None:
        self.repo = repo
        self.search = search
        self.gitlab_enabled = gitlab_enabled

    def resolve_sha(self, token: str) -> str | None:
        full = self.search.commit_exists(token)
        if full:
            return full
        # İndekste olmayan (ör. henüz indekslenmemiş) ama git'te var olan commit'ler de geçerli.
        resolved = self.repo.resolve(token)
        if resolved and resolved.startswith(token):
            return resolved
        return None

    def verify(self, text: str) -> CitationReport:
        report = CitationReport()
        for token in extract_shas(text):
            full = self.resolve_sha(token)
            if full:
                report.valid_shas[token] = full
            else:
                report.invalid_shas.append(token)
        for iid in extract_mrs(text):
            if self.gitlab_enabled and self.search.mr_exists(iid):
                report.valid_mrs.append(iid)
            else:
                report.invalid_mrs.append(iid)
        return report


def mark_unverified(text: str, report: CitationReport) -> str:
    """Doğrulanamayan referansların yanına uyarı ekler."""
    for token in report.invalid_shas:
        text = re.sub(
            rf"(?<![0-9a-zA-Z_/\-.]){re.escape(token)}(?![0-9a-zA-Z_\-])",
            f"{token} ({warning_label()})",
            text,
        )
    for iid in report.invalid_mrs:
        text = re.sub(rf"(?<![\w&])!{iid}\b", f"!{iid} ({warning_label()})", text)
    return text
