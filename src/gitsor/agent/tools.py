"""LLM'e açılan araçlar: şemalar (tek kaynak) ve yürütücü.

Araç çıktıları küçük modellerin de rahat okuyabileceği sade metindir. Her çıktı karakter
bütçesine göre kırpılır, kırpıldığı belirtilir ve LLM'e gitmeden önce `redact` edilir.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import date
from typing import Any

from gitsor.config import Config
from gitsor.errors import GitsorError
from gitsor.git.models import Commit
from gitsor.git.reader import GitRepo
from gitsor.index.db import Database
from gitsor.index.search import FTSSearch, MRQuery, SearchQuery
from gitsor.llm.base import ToolSpec
from gitsor.redact import redact

GITLAB_TOOLS = frozenset({"search_mrs", "get_mr"})

_DATE = {"type": "string", "description": "YYYY-MM-DD"}

TOOL_SPECS: list[ToolSpec] = [
    ToolSpec(
        "search_commits",
        "Commit mesajlarında tam metin araması (Türkçe/İngilizce). Dosya yolu, yazar ve tarih "
        "filtreleri alır. Konu/özellik bazlı sorular için ilk adım.",
        {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "Anahtar kelimeler"},
                "path": {"type": "string", "description": "Dosya ya da dizin yolu (glob olabilir)"},
                "author": {"type": "string", "description": "Yazar adı ya da e-postası (kısmi)"},
                "since": _DATE,
                "until": _DATE,
                "limit": {"type": "integer", "minimum": 1, "maximum": 50},
            },
            "required": [],
        },
    ),
    ToolSpec(
        "pickaxe",
        "Kodda bir string'in (ya da regex'in) eklendiği/kaldırıldığı commit'leri bulur "
        "(git log -S/-G). 'X ne zaman eklendi/kaldırıldı' sorularının ana aracı. Sonuçlar "
        "yeniden eskiye sıralıdır; en alttaki ilk ortaya çıkıştır.",
        {
            "type": "object",
            "properties": {
                "term": {
                    "type": "string",
                    "description": "Kodda aranacak birebir metin ya da regex",
                },
                "regex": {"type": "boolean", "description": "true ise term bir regex'tir (-G)"},
                "path": {"type": "string"},
                "limit": {"type": "integer", "minimum": 1, "maximum": 50},
            },
            "required": ["term"],
        },
    ),
    ToolSpec(
        "file_history",
        "Bir dosyanın commit geçmişi (rename takipli), yeniden eskiye.",
        {
            "type": "object",
            "properties": {
                "path": {"type": "string"},
                "since": _DATE,
                "until": _DATE,
                "limit": {"type": "integer", "minimum": 1, "maximum": 100},
            },
            "required": ["path"],
        },
    ),
    ToolSpec(
        "line_history",
        "Bir dosyadaki satır aralığının evrimi (git log -L): her commit'te o satırların nasıl değiştiği.",
        {
            "type": "object",
            "properties": {
                "path": {"type": "string"},
                "start": {"type": "integer", "minimum": 1},
                "end": {"type": "integer", "minimum": 1},
            },
            "required": ["path", "start", "end"],
        },
    ),
    ToolSpec(
        "blame",
        "Satırların en son hangi commit'te değiştiğini gösterir (git blame).",
        {
            "type": "object",
            "properties": {
                "path": {"type": "string"},
                "start": {"type": "integer", "minimum": 1},
                "end": {"type": "integer", "minimum": 1},
            },
            "required": ["path"],
        },
    ),
    ToolSpec(
        "get_commit",
        "Bir commit'in detayı: yazar, tarih, mesaj, değişen dosyalar, içinde bulunduğu tag/branch'ler, "
        "bağlı MR ve (izin varsa) kırpılmış diff.",
        {
            "type": "object",
            "properties": {
                "sha": {"type": "string", "description": "Tam ya da kısa SHA"},
                "include_diff": {"type": "boolean"},
            },
            "required": ["sha"],
        },
    ),
    ToolSpec(
        "search_mrs",
        "GitLab merge request'lerinde (başlık, açıklama, review yorumları, bağlı issue'lar) arama. "
        "'Neden' sorularında gerekçeyi bulmak için kullan.",
        {
            "type": "object",
            "properties": {
                "query": {"type": "string"},
                "state": {"type": "string", "enum": ["merged", "opened", "closed"]},
                "since": _DATE,
                "until": _DATE,
            },
            "required": ["query"],
        },
    ),
    ToolSpec(
        "get_mr",
        "Bir merge request'in detayı: açıklama, commit'leri, review yorumları, bağlı issue'lar.",
        {
            "type": "object",
            "properties": {"iid": {"type": "integer", "description": "MR numarası (!123 -> 123)"}},
            "required": ["iid"],
        },
    ),
    ToolSpec(
        "list_paths",
        "Repodaki dosya yollarını glob (`**/*.py`) ya da alt dize (`login`) ile bulur. "
        "Doğru dosya yolunu bilmiyorsan önce bunu kullan.",
        {
            "type": "object",
            "properties": {"pattern": {"type": "string"}},
            "required": ["pattern"],
        },
    ),
]


@dataclass
class ToolResult:
    text: str
    truncated: bool = False
    is_error: bool = False


@dataclass
class Toolbox:
    """Araç yürütücü. Görülen SHA ve MR'ları kaynak listesi ve doğrulama için toplar."""

    repo: GitRepo
    db: Database
    config: Config
    budget: int = 8000
    seen_shas: set[str] = field(default_factory=set)
    seen_mrs: set[int] = field(default_factory=set)

    def __post_init__(self) -> None:
        self.search = FTSSearch(self.db)
        self.budget = self.config.llm.tool_output_chars
        self._handlers: dict[str, Callable[[dict[str, Any]], str]] = {
            "search_commits": self._search_commits,
            "pickaxe": self._pickaxe,
            "file_history": self._file_history,
            "line_history": self._line_history,
            "blame": self._blame,
            "get_commit": self._get_commit,
            "search_mrs": self._search_mrs,
            "get_mr": self._get_mr,
            "list_paths": self._list_paths,
        }

    @property
    def gitlab_enabled(self) -> bool:
        return self.config.gitlab.enabled

    def specs(self) -> list[ToolSpec]:
        return [s for s in TOOL_SPECS if self.gitlab_enabled or s.name not in GITLAB_TOOLS]

    def execute(self, name: str, args: dict[str, Any]) -> ToolResult:
        handler = self._handlers.get(name)
        if handler is None or (name in GITLAB_TOOLS and not self.gitlab_enabled):
            return ToolResult(f"Bilinmeyen araç: {name}", is_error=True)
        try:
            text = handler(args)
        except (GitsorError, ValueError, TypeError, KeyError) as exc:
            return ToolResult(f"Hata: {exc}", is_error=True)
        return self._finish(text)

    def _finish(self, text: str, budget: int | None = None) -> ToolResult:
        limit = budget or self.budget
        text = redact(text)
        if len(text) <= limit:
            return ToolResult(text)
        cut = text[:limit].rsplit("\n", 1)[0]
        return ToolResult(
            cut + f"\n… (çıktı kırpıldı: {len(text) - len(cut)} karakter gösterilmedi; "
            "daha dar bir sorgu, limit ya da tarih aralığı kullan)",
            truncated=True,
        )

    # ------------------------------------------------------------------ biçimleme

    def _remember(self, sha: str) -> None:
        self.seen_shas.add(sha)

    def _commit_line(self, c: Commit, extra: str = "") -> str:
        self._remember(c.sha)
        files = ", ".join(f.path for f in c.files[:5])
        if len(c.files) > 5:
            files += f" (+{len(c.files) - 5} dosya)"
        merge = " [merge]" if c.is_merge else ""
        line = f"- {c.short_sha} {c.author_date.date()} {c.author_name}{merge}: {c.subject}"
        if extra:
            line += f" {extra}"
        if files:
            line += f"\n    dosyalar: {files}"
        return line

    def _mr_refs(self, sha: str) -> str:
        if not self.gitlab_enabled:
            return ""
        mrs = self.search.mrs_for_commit(sha)
        for m in mrs:
            self.seen_mrs.add(m.iid)
        return ", ".join(f"!{m.iid} {m.title} ({m.web_url})" for m in mrs)

    # ------------------------------------------------------------------ araçlar

    def _search_commits(self, args: dict[str, Any]) -> str:
        q = SearchQuery(
            text=args.get("query") or None,
            path=args.get("path") or None,
            author=args.get("author") or None,
            since=_parse_date(args.get("since")),
            until=_parse_date(args.get("until")),
            limit=_limit(args.get("limit"), 15, 50),
        )
        hits = self.search.search_commits(q)
        if not hits:
            return "Sonuç yok. Farklı anahtar kelimeler, pickaxe ya da file_history deneyin."
        lines = [f"{len(hits)} commit bulundu:"]
        for h in hits:
            self._remember(h.sha)
            merge = " [merge]" if h.is_merge else ""
            files = ", ".join(h.files[:4]) + (" …" if len(h.files) > 4 else "")
            lines.append(
                f"- {h.short_sha} {h.author_date[:10]} {h.author_name}{merge}: {h.subject}"
            )
            if files:
                lines.append(f"    dosyalar: {files}")
        return "\n".join(lines)

    def _pickaxe(self, args: dict[str, Any]) -> str:
        term = str(args.get("term") or "")
        if not term:
            raise ValueError("term boş olamaz")
        hits = self.repo.pickaxe(
            term,
            regex=bool(args.get("regex")),
            path=args.get("path") or None,
            limit=_limit(args.get("limit"), 20, 50),
        )
        if not hits:
            return f"'{term}' için ekleme/kaldırma yapan commit bulunamadı (HEAD geçmişinde)."
        lines = [f"'{term}' içeren değişiklikler (yeniden eskiye; sonuncusu ilk ortaya çıkış):"]
        for h in hits:
            lines.append(self._commit_line(h.commit, f"→ {h.kind} (+{h.added}/-{h.removed} satır)"))
        return "\n".join(lines)

    def _file_history(self, args: dict[str, Any]) -> str:
        path = str(args["path"])
        commits = self.repo.file_history(
            path,
            since=_parse_date(args.get("since")),
            until=_parse_date(args.get("until")),
            limit=_limit(args.get("limit"), 30, 100),
        )
        if not commits:
            return f"'{path}' için geçmiş yok. Doğru yol için list_paths kullanın."
        lines = [f"'{path}' geçmişi ({len(commits)} commit, yeniden eskiye):"]
        for c in commits:
            stat = next((f for f in c.files), None)
            extra = ""
            if stat is not None:
                if stat.status == "R" and stat.old_path:
                    extra = f"(yeniden adlandırma: {stat.old_path} → {stat.path})"
                elif stat.status in ("A", "D"):
                    extra = "(dosya eklendi)" if stat.status == "A" else "(dosya silindi)"
                elif stat.additions is not None:
                    extra = f"(+{stat.additions}/-{stat.deletions})"
            self._remember(c.sha)
            lines.append(
                f"- {c.short_sha} {c.author_date.date()} {c.author_name}: {c.subject} {extra}".rstrip()
            )
        return "\n".join(lines)

    def _line_history(self, args: dict[str, Any]) -> str:
        path, start, end = str(args["path"]), int(args["start"]), int(args["end"])
        if end < start:
            start, end = end, start
        entries = self.repo.line_history(path, start, end, limit=20)
        if not entries:
            return f"{path}:{start}-{end} için geçmiş bulunamadı."
        send_diffs = self.config.privacy.send_diffs
        lines = [f"{path}:{start}-{end} satırlarının evrimi (yeniden eskiye):"]
        per_entry = max(400, self.budget // max(1, len(entries)))
        for e in entries:
            lines.append(self._commit_line(e.commit))
            if send_diffs:
                diff = "\n".join(
                    ln
                    for ln in e.diff.splitlines()
                    if ln[:1] in "+-@ " and not ln.startswith(("+++", "---"))
                )
                lines.append(_indent(diff[:per_entry]))
        return "\n".join(lines)

    def _blame(self, args: dict[str, Any]) -> str:
        path = str(args["path"])
        start = args.get("start")
        end = args.get("end")
        if start is None and end is not None:
            start = 1
        if start is not None and end is None:
            end = int(start) + 40
        lines_ = self.repo.blame(path, int(start) if start else None, int(end) if end else None)
        if not lines_:
            return "blame sonucu boş."
        send_code = self.config.privacy.send_diffs
        out = [f"{path} blame:"]
        for b in lines_[:200]:
            self._remember(b.sha)
            text = f"  | {b.content}" if send_code else ""
            out.append(
                f"{b.line_no:>5} {b.sha[:7]} {b.author_date.date()} {b.author_name}: {b.summary}{text}"
            )
        if len(lines_) > 200:
            out.append(f"… ({len(lines_) - 200} satır daha; start/end ile daraltın)")
        return "\n".join(out)

    def _get_commit(self, args: dict[str, Any]) -> str:
        rev = str(args["sha"]).strip()
        commit = self.repo.get_commit(rev)
        if commit is None:
            return f"'{rev}' adlı bir commit bulunamadı."
        self._remember(commit.sha)
        out = [
            f"commit {commit.sha} (kısa: {commit.short_sha})",
            f"yazar: {commit.author_name} <{commit.author_email}>",
            f"tarih: {commit.author_date.date()} (commit: {commit.committer_date.date()})",
        ]
        if commit.is_merge:
            out.append(f"merge commit; parent'lar: {', '.join(p[:7] for p in commit.parents)}")
        tags = self.repo.tags_containing(commit.sha)
        if tags:
            out.append(
                f"ilk yer aldığı tag: {tags[0]}"
                + (f" (toplam {len(tags)} tag)" if len(tags) > 1 else "")
            )
        branches = self.repo.branches_containing(commit.sha)
        if branches:
            out.append("branch'ler: " + ", ".join(branches[:8]))
        if mrs := self._mr_refs(commit.sha):
            out.append(f"bağlı MR: {mrs}")
        out.append("")
        out.append(commit.message)
        out.append("")
        out.append("değişen dosyalar:")
        for f in commit.files[:40]:
            ren = f" (önceki: {f.old_path})" if f.old_path else ""
            stat = "ikili" if f.additions is None else f"+{f.additions}/-{f.deletions}"
            out.append(f"  {f.status} {f.path}{ren} {stat}")
        if len(commit.files) > 40:
            out.append(f"  … ve {len(commit.files) - 40} dosya daha")
        include_diff = args.get("include_diff", True)
        privacy = self.config.privacy
        if include_diff and privacy.send_diffs and privacy.max_diff_chars > 0:
            header = "\n".join(out)
            room = max(500, min(privacy.max_diff_chars, self.budget - len(header) - 200))
            diff = self.repo.diff(commit.sha, max_chars=room, exclude_paths=privacy.exclude_paths)
            out.append("")
            out.append("diff:" + (" (kırpıldı)" if diff.truncated else ""))
            if diff.excluded_paths:
                out.append(
                    f"(gizlilik nedeniyle diff'i gönderilmeyen dosyalar: {', '.join(diff.excluded_paths)})"
                )
            out.append(diff.text)
        elif include_diff and not privacy.send_diffs:
            out.append("\n(diff gönderimi config ile kapalı)")
        return "\n".join(out)

    def _search_mrs(self, args: dict[str, Any]) -> str:
        hits = self.search.search_mrs(
            MRQuery(
                text=args.get("query") or None,
                state=args.get("state") or None,
                since=_parse_date(args.get("since")),
                until=_parse_date(args.get("until")),
                limit=10,
            )
        )
        if not hits:
            return "Eşleşen MR yok."
        lines = [f"{len(hits)} MR bulundu:"]
        for h in hits:
            self.seen_mrs.add(h.iid)
            when = (h.merged_at or "")[:10] or h.state
            where = f" [eşleşme: {', '.join(h.matched_in)}]" if h.matched_in else ""
            lines.append(f"- !{h.iid} {when} {h.author or '?'}: {h.title} ({h.web_url}){where}")
        return "\n".join(lines)

    def _get_mr(self, args: dict[str, Any]) -> str:
        iid = int(str(args["iid"]).lstrip("!"))
        mr = self.search.get_mr(iid)
        if mr is None:
            return f"!{iid} indekste yok (gitsor sync çalıştırıldı mı?)."
        self.seen_mrs.add(iid)
        out = [
            f"!{mr.iid} {mr.title}",
            f"durum: {mr.state}, yazar: {mr.author}, {mr.source_branch} → {mr.target_branch}",
            f"oluşturma: {(mr.created_at or '')[:10]}, merge: {(mr.merged_at or '-')[:10]}",
            f"link: {mr.web_url}",
        ]
        shas = list(mr.commits)
        for extra in (mr.merge_commit_sha, mr.squash_commit_sha):
            if extra and extra not in shas:
                shas.append(extra)
        known = [s for s in shas if self.search.commit_exists(s)]
        for s in known:
            self._remember(s)
        if shas:
            out.append("commit'ler: " + ", ".join(s[:7] for s in shas[:30]))
        if mr.merge_commit_sha:
            out.append(f"merge commit: {mr.merge_commit_sha[:7]}")
        if mr.squash_commit_sha:
            out.append(f"squash commit: {mr.squash_commit_sha[:7]}")
        out += ["", "açıklama:", mr.description.strip() or "(boş)"]
        if mr.issues:
            out.append("\nbağlı issue'lar:")
            for i in mr.issues:
                labels = ", ".join(str(x) for x in i.get("labels", []))  # type: ignore[attr-defined]
                out.append(
                    f"- #{i['iid']} ({i['relation']}) {i['title']} [{labels}] {i.get('web_url') or ''}"
                )
                desc = str(i.get("description") or "").strip()
                if desc:
                    out.append(_indent(desc[:800]))
        if mr.notes:
            out.append("\nreview yorumları:")
            for n in mr.notes:
                loc = f" ({n['file_path']}:{n['line']})" if n.get("file_path") else ""
                out.append(
                    f"- {n.get('author')} {str(n.get('created_at') or '')[:10]}{loc}: {n['body']}"
                )
        return "\n".join(out)

    def _list_paths(self, args: dict[str, Any]) -> str:
        pattern = str(args.get("pattern") or "*")
        paths = self.repo.list_paths(pattern, limit=200)
        if not paths:
            if self.repo.path_exists_in_history(pattern):
                return (
                    f"'{pattern}' artık HEAD'de yok ama geçmişte var (silinmiş/taşınmış olabilir)."
                )
            return f"'{pattern}' ile eşleşen dosya yok."
        return f"{len(paths)} yol:\n" + "\n".join(paths)


def _indent(text: str, prefix: str = "    ") -> str:
    return "\n".join(prefix + ln for ln in text.splitlines())


def _limit(value: Any, default: int, maximum: int) -> int:
    try:
        n = int(value) if value is not None else default
    except (TypeError, ValueError):
        n = default
    return max(1, min(n, maximum))


def _parse_date(value: Any) -> date | None:
    if not value:
        return None
    if isinstance(value, date):
        return value
    text = str(value).strip()[:10]
    try:
        return date.fromisoformat(text)
    except ValueError:
        if len(text) == 7:  # YYYY-MM
            return date.fromisoformat(text + "-01")
        if len(text) == 4 and text.isdigit():
            return date(int(text), 1, 1)
        raise ValueError(f"Geçersiz tarih: {value} (YYYY-MM-DD bekleniyor)") from None
