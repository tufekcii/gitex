"""python-gitlab sarmalayıcı: yalnızca gitsor'un ihtiyaç duyduğu okuma çağrıları, sade dict'ler döner."""

from __future__ import annotations

from collections.abc import Iterator
from dataclasses import dataclass, field
from typing import Any

from gitsor.config import GitLabConfig
from gitsor.errors import GitLabError

WANTED_STATES = frozenset({"merged", "opened"})


@dataclass
class MRData:
    iid: int
    title: str
    description: str
    state: str
    author: str | None
    source_branch: str | None
    target_branch: str | None
    web_url: str | None
    created_at: str | None
    updated_at: str | None
    merged_at: str | None
    merge_commit_sha: str | None
    squash_commit_sha: str | None
    commits: list[str] = field(default_factory=list)
    notes: list[dict[str, Any]] = field(default_factory=list)
    issues: list[dict[str, Any]] = field(default_factory=list)  # + "relation": closes | related


def _username(user: Any) -> str | None:
    if isinstance(user, dict):
        return user.get("username") or user.get("name")
    return None


class GitLabClient:
    def __init__(self, cfg: GitLabConfig, token: str | None, gl: Any = None) -> None:
        if not cfg.project:
            raise GitLabError(
                "GitLab projesi ayarlanmamış.", hint='[gitlab] project = "grup/proje"'
            )
        self.cfg = cfg
        if gl is None:
            import gitlab

            gl = gitlab.Gitlab(
                cfg.url,
                private_token=token,
                per_page=cfg.per_page,
                retry_transient_errors=True,
                timeout=60,
            )
        self.gl = gl
        self.project = gl.projects.get(cfg.project, lazy=True)
        # 429'da Retry-After'a uyarak bekler (python-gitlab: obey_rate_limit varsayılan açık).
        self._kw: dict[str, Any] = {"max_retries": cfg.max_retries, "obey_rate_limit": True}

    def _wrap(self, exc: Exception) -> GitLabError:
        import gitlab

        if isinstance(exc, gitlab.GitlabAuthenticationError):
            return GitLabError(
                "GitLab kimlik doğrulaması başarısız.",
                hint="GITSOR_GITLAB_TOKEN ortam değişkenine `read_api` yetkili bir token verin.",
            )
        if (
            isinstance(exc, gitlab.GitlabGetError | gitlab.GitlabListError)
            and getattr(exc, "response_code", None) == 404
        ):
            return GitLabError(
                f"GitLab projesi bulunamadı: {self.cfg.project}",
                hint="`gitlab.project` (grup/proje ya da ID) ve token yetkisini kontrol edin.",
            )
        if isinstance(exc, gitlab.GitlabHttpError | gitlab.GitlabError):
            return GitLabError(f"GitLab hatası: {exc}")
        return GitLabError(
            f"GitLab'a ulaşılamıyor ({self.cfg.url}): {exc}",
            hint="`gitlab.url` ve ağ bağlantısını kontrol edin.",
        )

    def iter_merge_requests(self, updated_after: str | None = None) -> Iterator[dict[str, Any]]:
        """Güncellenme sırasıyla (eskiden yeniye) tüm MR'lar; kapalı olanlar da döner (silmek için)."""
        import requests

        params: dict[str, Any] = {
            "state": "all",
            "order_by": "updated_at",
            "sort": "asc",
            "iterator": True,
        }
        if updated_after:
            params["updated_after"] = updated_after
        try:
            for mr in self.project.mergerequests.list(**params, **self._kw):
                yield dict(mr.attributes)
        except Exception as exc:
            if isinstance(exc, requests.RequestException) or _is_gitlab_error(exc):
                raise self._wrap(exc) from exc
            raise

    def fetch_details(self, raw: dict[str, Any]) -> MRData:
        """Bir MR'ın commit'lerini, (sistem dışı) notlarını ve bağlı issue'larını çeker."""
        import requests

        iid = int(raw["iid"])
        data = MRData(
            iid=iid,
            title=raw.get("title") or "",
            description=raw.get("description") or "",
            state=raw.get("state") or "",
            author=_username(raw.get("author")),
            source_branch=raw.get("source_branch"),
            target_branch=raw.get("target_branch"),
            web_url=raw.get("web_url"),
            created_at=raw.get("created_at"),
            updated_at=raw.get("updated_at"),
            merged_at=raw.get("merged_at"),
            merge_commit_sha=raw.get("merge_commit_sha"),
            squash_commit_sha=raw.get("squash_commit_sha"),
        )
        mr = self.project.mergerequests.get(iid, lazy=True)
        try:
            data.commits = [c.attributes["id"] for c in mr.commits(**self._kw)]
            for note in mr.notes.list(iterator=True, **self._kw):
                n = note.attributes
                if n.get("system"):
                    continue
                pos = n.get("position") or {}
                data.notes.append(
                    {
                        "id": int(n["id"]),
                        "author": _username(n.get("author")),
                        "body": n.get("body") or "",
                        "created_at": n.get("created_at"),
                        "file_path": pos.get("new_path") or pos.get("old_path"),
                        "line": pos.get("new_line") or pos.get("old_line"),
                    }
                )
            seen: set[int] = set()
            for relation, fetch in (("closes", mr.closes_issues), ("related", mr.related_issues)):
                for issue in fetch(**self._kw):
                    a = issue.attributes
                    if int(a["iid"]) in seen:
                        continue
                    seen.add(int(a["iid"]))
                    data.issues.append(
                        {
                            "iid": int(a["iid"]),
                            "title": a.get("title") or "",
                            "description": a.get("description") or "",
                            "state": a.get("state"),
                            "labels": list(a.get("labels") or []),
                            "author": _username(a.get("author")),
                            "web_url": a.get("web_url"),
                            "created_at": a.get("created_at"),
                            "updated_at": a.get("updated_at"),
                            "closed_at": a.get("closed_at"),
                            "relation": relation,
                        }
                    )
        except Exception as exc:
            if isinstance(exc, requests.RequestException) or _is_gitlab_error(exc):
                raise self._wrap(exc) from exc
            raise
        return data


def _is_gitlab_error(exc: Exception) -> bool:
    import gitlab

    return isinstance(exc, gitlab.GitlabError)
