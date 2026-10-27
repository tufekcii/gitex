"""`git` CLI'ını subprocess ile çağırıp makine-okunur çıktıyı parse eden okuyucu.

GitPython kullanılmaz; tüm alanlar NUL / ASCII ayraçlı formatlarla alınır.
"""

from __future__ import annotations

import os
import re
import subprocess
from collections.abc import Iterable, Iterator, Sequence
from datetime import date, datetime, timedelta, timezone, tzinfo
from pathlib import Path

from gitsor.errors import GitCommandError, NotAGitRepoError
from gitsor.git.models import (
    BlameLine,
    Commit,
    DiffText,
    FileChange,
    Hunk,
    LineHistoryEntry,
    PickaxeHit,
    Ref,
)
from gitsor.git.pathmatch import has_glob, match_any, match_path

_REC = "\x1e"
_SEP = "\x1f"
_HEADER_FIELDS = ("%H", "%P", "%an", "%ae", "%aI", "%cn", "%ce", "%cI", "%B")
LOG_FORMAT = "%x1e" + "%x1f".join(_HEADER_FIELDS) + "%x1f"

_NUMSTAT_RE = re.compile(r"^(\d+|-)\t(\d+|-)\t(.*)$", re.DOTALL)
_HUNK_RE = re.compile(r"^@@ -(\d+)(?:,(\d+))? \+(\d+)(?:,(\d+))? @@(.*)$")

# Parse edilen çıktının dilden bağımsız olması ve sayfalayıcı açılmaması için.
_GIT_ENV = {"LC_ALL": "C", "LANG": "C", "GIT_PAGER": "cat", "GIT_TERMINAL_PROMPT": "0"}
_GIT_OPTS = ("-c", "core.quotepath=false", "-c", "log.showSignature=false", "-c", "color.ui=never")


def _date_arg(value: date | datetime | str) -> str:
    return value.isoformat() if isinstance(value, date | datetime) else value


def parse_hunks(diff: str) -> list[Hunk]:
    hunks: list[Hunk] = []
    current: tuple[int, int, int, int, str] | None = None
    lines: list[str] = []
    for line in diff.splitlines():
        m = _HUNK_RE.match(line)
        if m:
            if current:
                hunks.append(Hunk(*current, lines=tuple(lines)))
            current = (
                int(m.group(1)),
                int(m.group(2) or 1),
                int(m.group(3)),
                int(m.group(4) or 1),
                m.group(5).strip(),
            )
            lines = []
        elif current and line[:1] in ("+", "-", " ", "\\"):
            lines.append(line)
    if current:
        hunks.append(Hunk(*current, lines=tuple(lines)))
    return hunks


def split_diff_by_file(patch: str) -> list[tuple[str, str]]:
    """Bir patch'i `(path, dosya_diff'i)` çiftlerine böler."""
    parts: list[tuple[str, str]] = []
    for chunk in re.split(r"(?m)^(?=diff --git )", patch):
        if not chunk.startswith("diff --git "):
            continue
        path = ""
        for line in chunk.splitlines():
            if line.startswith("+++ "):
                target = line[4:]
                if target != "/dev/null":
                    path = target[2:] if target.startswith("b/") else target
            elif line.startswith("--- ") and not path:
                source = line[4:]
                if source != "/dev/null":
                    path = source[2:] if source.startswith("a/") else source
            elif line.startswith("rename to "):
                path = line[len("rename to ") :]
        if not path:
            # İkili ya da yalnızca mod değişikliği: başlıktan çıkar.
            m = re.match(r"diff --git a/(.*) b/(.*)", chunk.splitlines()[0])
            path = m.group(2) if m else ""
        parts.append((path, chunk))
    return parts


class GitRepo:
    """Tek bir yerel git deposu üzerinde okuma işlemleri."""

    def __init__(self, path: str | Path = ".") -> None:
        start = Path(path).resolve()
        try:
            out = self._exec(start, ["rev-parse", "--show-toplevel"])
        except GitCommandError as exc:
            raise NotAGitRepoError(
                f"'{start}' bir git deposu değil.",
                hint="Bir git deposunun içinde çalıştırın ya da `--repo` ile yol verin.",
            ) from exc
        self.root = Path(out.strip()).resolve()

    # ------------------------------------------------------------------ altyapı

    @staticmethod
    def _exec(
        cwd: Path,
        args: Sequence[str],
        *,
        input_text: str | None = None,
        ok_codes: tuple[int, ...] = (0,),
    ) -> str:
        env = {**os.environ, **_GIT_ENV}
        try:
            proc = subprocess.run(
                ["git", *_GIT_OPTS, *args],
                cwd=cwd,
                input=input_text.encode() if input_text is not None else None,
                capture_output=True,
                env=env,
                check=False,
            )
        except FileNotFoundError as exc:
            raise GitCommandError(
                "`git` komutu bulunamadı.", hint="git'in kurulu ve PATH'te olduğundan emin olun."
            ) from exc
        if proc.returncode not in ok_codes:
            err = proc.stderr.decode("utf-8", "replace").strip()
            raise GitCommandError(f"git {' '.join(args[:3])} başarısız: {err}")
        return proc.stdout.decode("utf-8", "replace")

    def run(
        self,
        args: Sequence[str],
        *,
        input_text: str | None = None,
        ok_codes: tuple[int, ...] = (0,),
    ) -> str:
        return self._exec(self.root, args, input_text=input_text, ok_codes=ok_codes)

    # ------------------------------------------------------------------ temel

    def head(self) -> str | None:
        out = self.run(["rev-parse", "--verify", "--quiet", "HEAD"], ok_codes=(0, 1))
        return out.strip() or None

    def is_empty(self) -> bool:
        return self.head() is None and not self.all_commit_shas()

    def resolve(self, rev: str) -> str | None:
        """Bir SHA önekini / ref'i tam commit SHA'sına çevirir; yoksa None."""
        if not rev or rev.startswith("-"):
            return None
        out = self.run(
            ["rev-parse", "--verify", "--quiet", f"{rev}^{{commit}}"], ok_codes=(0, 1, 128)
        )
        return out.strip() or None

    def all_commit_shas(self) -> list[str]:
        out = self.run(["rev-list", "--exclude=refs/stash", "--all"])
        return out.split()

    def list_refs(self) -> list[Ref]:
        fmt = "%(refname)%00%(objectname)%00%(*objectname)"
        out = self.run(
            ["for-each-ref", f"--format={fmt}", "refs/heads", "refs/remotes", "refs/tags"]
        )
        refs: list[Ref] = []
        for line in out.splitlines():
            name, obj, peeled = ([*line.split("\x00"), "", ""])[:3]
            if name.startswith("refs/heads/"):
                refs.append(Ref(name.removeprefix("refs/heads/"), obj, "branch"))
            elif name.startswith("refs/remotes/"):
                if name.endswith("/HEAD"):
                    continue
                refs.append(Ref(name.removeprefix("refs/remotes/"), obj, "remote"))
            elif name.startswith("refs/tags/"):
                refs.append(Ref(name.removeprefix("refs/tags/"), peeled or obj, "tag"))
        return refs

    def refs_fingerprint(self) -> str:
        """Ref'ler değiştiğinde değişen kısa bir parmak izi (indeks tazelik kontrolü)."""
        refs = sorted(f"{r.kind}:{r.name}:{r.sha}" for r in self.list_refs())
        return f"{self.head() or ''}|{'|'.join(refs)}"

    # ------------------------------------------------------------------ log parse

    def _log(self, args: Sequence[str], *, input_text: str | None = None) -> list[Commit]:
        out = self.run(
            [
                "log",
                "-z",
                f"--format={LOG_FORMAT}",
                "--raw",
                "--numstat",
                "--no-abbrev",
                "--diff-merges=first-parent",
                "-M",
                *args,
            ],
            input_text=input_text,
        )
        return list(self._parse_log(out))

    @staticmethod
    def _parse_header(fields: list[str]) -> Commit:
        sha, parents, an, ae, ad, cn, ce, cd, message = fields[:9]
        subject, _, body = message.strip("\n").partition("\n")
        return Commit(
            sha=sha.strip(),
            parents=tuple(parents.split()),
            author_name=an,
            author_email=ae,
            author_date=datetime.fromisoformat(ad),
            committer_name=cn,
            committer_email=ce,
            committer_date=datetime.fromisoformat(cd),
            subject=subject.strip(),
            body=body.strip(),
        )

    @classmethod
    def _parse_log(cls, out: str) -> Iterator[Commit]:
        for record in out.split(_REC):
            if not record.strip("\x00\n"):
                continue
            fields = record.split(_SEP, 9)
            if len(fields) < 10:
                continue
            base = cls._parse_header(fields)
            files = cls._parse_changes(fields[9])
            yield Commit(
                sha=base.sha,
                parents=base.parents,
                author_name=base.author_name,
                author_email=base.author_email,
                author_date=base.author_date,
                committer_name=base.committer_name,
                committer_email=base.committer_email,
                committer_date=base.committer_date,
                subject=base.subject,
                body=base.body,
                files=tuple(files),
            )

    @staticmethod
    def _parse_changes(text: str) -> list[FileChange]:
        tokens = [t.lstrip("\n") for t in text.split("\x00")]
        raw: list[tuple[str, str, str | None]] = []  # (status, path, old_path)
        stats: dict[str, tuple[int | None, int | None]] = {}
        i = 0
        while i < len(tokens):
            tok = tokens[i]
            if not tok:
                i += 1
                continue
            if tok.startswith(":"):
                status = tok.split()[-1]
                letter = status[:1]
                if letter in ("R", "C") and i + 2 < len(tokens):
                    raw.append((letter, tokens[i + 2], tokens[i + 1]))
                    i += 3
                elif i + 1 < len(tokens):
                    raw.append((letter, tokens[i + 1], None))
                    i += 2
                else:
                    i += 1
                continue
            m = _NUMSTAT_RE.match(tok)
            if m:
                add = None if m.group(1) == "-" else int(m.group(1))
                dele = None if m.group(2) == "-" else int(m.group(2))
                path = m.group(3)
                if path == "" and i + 2 < len(tokens):
                    path = tokens[i + 2]
                    i += 3
                else:
                    i += 1
                stats[path] = (add, dele)
                continue
            i += 1
        changes: list[FileChange] = []
        for status, path, old in raw:
            add, dele = stats.get(path, (None, None))
            changes.append(
                FileChange(path=path, status=status, old_path=old, additions=add, deletions=dele)
            )
        return changes

    # ------------------------------------------------------------------ sorgular

    def list_commits(
        self,
        *,
        revs: Sequence[str] = (),
        path: str | None = None,
        author: str | None = None,
        since: date | datetime | str | None = None,
        until: date | datetime | str | None = None,
        limit: int | None = None,
        all_refs: bool = False,
    ) -> list[Commit]:
        if self.head() is None and not all_refs:
            return []
        args: list[str] = []
        if limit:
            args.append(f"--max-count={limit}")
        if author:
            args += ["-i", f"--author={author}"]
        if since:
            args.append(f"--since={_date_arg(since)}")
        if until:
            args.append(f"--until={_date_arg(until)}")
        if all_refs:
            args += ["--exclude=refs/stash", "--all"]
        args += list(revs)
        if path:
            args += ["--", path]
        return self._log(args)

    def commits_by_sha(self, shas: Iterable[str]) -> list[Commit]:
        """Verilen SHA'ların detaylarını tek bir `git log --stdin --no-walk` ile okur."""
        sha_list = list(shas)
        if not sha_list:
            return []
        return self._log(["--no-walk=unsorted", "--stdin"], input_text="\n".join(sha_list) + "\n")

    def get_commit(self, rev: str) -> Commit | None:
        sha = self.resolve(rev)
        if sha is None:
            return None
        commits = self.commits_by_sha([sha])
        return commits[0] if commits else None

    def diff(
        self,
        sha: str,
        *,
        max_chars: int = 12000,
        exclude_paths: Sequence[str] = (),
        paths: Sequence[str] = (),
    ) -> DiffText:
        """Commit'in (merge ise ilk parent'a göre) patch'i; hariç yollar atlanır, boyut kırpılır."""
        out = self.run(
            ["show", "--format=", "--patch", "--no-color", "--diff-merges=first-parent", "-M", sha]
        )
        kept: list[str] = []
        excluded: list[str] = []
        for path, chunk in split_diff_by_file(out):
            if exclude_paths and match_any(path, exclude_paths):
                excluded.append(path)
                continue
            if paths and not any(path == p or match_path(path, p) for p in paths):
                continue
            kept.append(chunk)
        text = "".join(kept)
        truncated = len(text) > max_chars
        if truncated:
            text = text[:max_chars]
        return DiffText(text=text, truncated=truncated, excluded_paths=tuple(excluded))

    def file_history(
        self,
        path: str,
        *,
        since: date | datetime | str | None = None,
        until: date | datetime | str | None = None,
        limit: int | None = None,
    ) -> list[Commit]:
        if self.head() is None:
            return []
        args = ["--follow"]
        if limit:
            args.append(f"--max-count={limit}")
        if since:
            args.append(f"--since={_date_arg(since)}")
        if until:
            args.append(f"--until={_date_arg(until)}")
        return self._log([*args, "--", path])

    def pickaxe(
        self,
        term: str,
        *,
        regex: bool = False,
        path: str | None = None,
        limit: int = 20,
        all_refs: bool = False,
    ) -> list[PickaxeHit]:
        """`git log -S` / `-G`: terimin eklendiği ya da kaldırıldığı commit'ler (yeniden eskiye)."""
        if self.head() is None:
            return []
        args = [f"-G{term}" if regex else f"-S{term}", f"--max-count={limit}"]
        if all_refs:
            args += ["--exclude=refs/stash", "--all"]
        if path:
            args += ["--", path]
        commits = self._log(args)
        matcher = re.compile(term) if regex else None
        hits: list[PickaxeHit] = []
        for commit in commits:
            patch = self.run(
                ["show", "--format=", "-U0", "--no-color", "--diff-merges=first-parent", commit.sha]
                + (["--", path] if path else [])
            )
            added = removed = 0
            for line in patch.splitlines():
                if line.startswith(("+++", "---")):
                    continue
                found = bool(matcher.search(line)) if matcher else term in line
                if not found:
                    continue
                if line.startswith("+"):
                    added += 1
                elif line.startswith("-"):
                    removed += 1
            hits.append(PickaxeHit(commit=commit, added=added, removed=removed))
        return hits

    def line_history(
        self, path: str, start: int, end: int, *, limit: int | None = None
    ) -> list[LineHistoryEntry]:
        if self.head() is None:
            return []
        args = ["log", f"--format={LOG_FORMAT}", "--no-color", f"-L{start},{end}:{path}"]
        if limit:
            args.append(f"--max-count={limit}")
        out = self.run(args)
        entries: list[LineHistoryEntry] = []
        for record in out.split(_REC):
            fields = record.split(_SEP, 9)
            if len(fields) < 10:
                continue
            commit = self._parse_header(fields)
            entries.append(LineHistoryEntry(commit=commit, diff=fields[9].strip("\n")))
        return entries

    def blame(
        self, path: str, start: int | None = None, end: int | None = None, rev: str = "HEAD"
    ) -> list[BlameLine]:
        args = ["blame", "--porcelain", "-M", "-C"]
        if start is not None:
            args.append(f"-L{start},{end if end is not None else ''}")
        args += [rev, "--", path]
        out = self.run(args)
        info: dict[str, dict[str, str]] = {}
        result: list[BlameLine] = []
        cur_sha = ""
        cur_orig = cur_final = 0
        for line in out.split("\n"):
            if not line:
                continue
            if line.startswith("\t"):
                meta = info[cur_sha]
                result.append(
                    BlameLine(
                        sha=cur_sha,
                        line_no=cur_final,
                        orig_line_no=cur_orig,
                        orig_path=meta.get("filename", path),
                        author_name=meta.get("author", ""),
                        author_email=meta.get("author-mail", "").strip("<>"),
                        author_date=datetime.fromtimestamp(
                            int(meta.get("author-time", "0")),
                            tz=_tz_from_offset(meta.get("author-tz", "+0000")),
                        ),
                        summary=meta.get("summary", ""),
                        content=line[1:],
                    )
                )
                continue
            parts = line.split(" ")
            if len(parts[0]) == 40 and all(c in "0123456789abcdef" for c in parts[0]):
                cur_sha = parts[0]
                cur_orig, cur_final = int(parts[1]), int(parts[2])
                info.setdefault(cur_sha, {})
            else:
                key, _, value = line.partition(" ")
                info.setdefault(cur_sha, {})[key] = value
        return result

    def tags_containing(self, sha: str) -> list[str]:
        return self.run(["tag", "--contains", sha, "--sort=creatordate"]).split()

    def branches_containing(self, sha: str) -> list[str]:
        out = self.run(["branch", "-a", "--contains", sha, "--format=%(refname:short)"])
        return [b for b in out.split() if not b.endswith("/HEAD")]

    def list_paths(self, pattern: str = "*", *, rev: str = "HEAD", limit: int = 200) -> list[str]:
        """HEAD ağacındaki dosya yolları; glob yoksa büyük/küçük harf duyarsız alt dize araması."""
        if self.head() is None:
            return []
        out = self.run(["ls-tree", "-r", "-z", "--name-only", rev])
        paths = [p for p in out.split("\x00") if p]
        if has_glob(pattern):
            matched = [p for p in paths if match_path(p, pattern)]
        else:
            needle = pattern.lower()
            matched = [p for p in paths if needle in p.lower()]
        return matched[:limit]

    def path_exists_in_history(self, path: str) -> bool:
        out = self.run(["log", "--all", "--max-count=1", "--format=%H", "--", path])
        return bool(out.strip())


def _tz_from_offset(offset: str) -> tzinfo:
    sign = -1 if offset.startswith("-") else 1
    digits = offset.lstrip("+-").zfill(4)
    return timezone(sign * timedelta(hours=int(digits[:2]), minutes=int(digits[2:])))
