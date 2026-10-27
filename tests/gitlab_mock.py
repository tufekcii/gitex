"""`responses` ile sahte GitLab API'si (ağa çıkmaz)."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from typing import Any
from urllib.parse import parse_qs, urlencode, urlparse

import responses

from gitsor.evals.fixture import FixtureRepo

BASE = "https://gitlab.example.com"
PROJECT = "grup/proje"
API = f"{BASE}/api/v4/projects/grup%2Fproje"


def _user(name: str) -> dict[str, Any]:
    return {"username": name, "name": name.title()}


def scenario(fx: FixtureRepo) -> dict[int, dict[str, Any]]:
    """Fixture deposuyla tutarlı MR senaryosu."""
    return {
        1: {
            "mr": {
                "iid": 1,
                "title": "İade (refund) desteği",
                "description": "Müşteri hizmetleri manuel iade yapamıyordu. Closes #7",
                "state": "merged",
                "author": _user("zeynep"),
                "source_branch": "feature/refund",
                "target_branch": "main",
                "web_url": f"{BASE}/{PROJECT}/-/merge_requests/1",
                "created_at": "2026-02-04T09:00:00Z",
                "updated_at": "2026-02-07T10:00:00Z",
                "merged_at": "2026-02-07T10:00:00Z",
                "merge_commit_sha": fx.sha("merge_refund"),
                "squash_commit_sha": None,
            },
            "commits": [fx.sha("refund")],
            "notes": [
                {"id": 101, "body": "added 1 commit", "system": True, "author": _user("zeynep")},
                {
                    "id": 102,
                    "body": "refund'da tutar kontrolü eksik, negatif tutar geçebilir",
                    "system": False,
                    "author": _user("ahmet"),
                    "created_at": "2026-02-05T12:00:00Z",
                    "position": {"new_path": "payment/service.py", "new_line": 12},
                },
                {
                    "id": 103,
                    "body": "Onaylıyorum, sonraki MR'da doğrulama eklenecek.",
                    "system": False,
                    "author": _user("mehmet"),
                    "created_at": "2026-02-06T08:00:00Z",
                },
            ],
            "closes_issues": [
                {
                    "iid": 7,
                    "title": "Müşteriler iade alamıyor",
                    "description": "Destek ekibi her iade için veritabanına elle müdahale ediyor.",
                    "state": "closed",
                    "labels": ["müşteri", "ödeme"],
                    "author": _user("ayse"),
                    "web_url": f"{BASE}/{PROJECT}/-/issues/7",
                }
            ],
            "related_issues": [],
        },
        2: {
            "mr": {
                "iid": 2,
                "title": "Kullanıcı silmeyi soft-delete yap",
                "description": "Silinen kullanıcıların izi denetim için korunmalı.",
                "state": "merged",
                "author": _user("zeynep"),
                "source_branch": "soft-delete",
                "target_branch": "main",
                "web_url": f"{BASE}/{PROJECT}/-/merge_requests/2",
                "created_at": "2026-02-25T09:00:00Z",
                "updated_at": "2026-03-01T10:00:00Z",
                "merged_at": "2026-03-01T10:00:00Z",
                "merge_commit_sha": None,
                # Squash merge: MR'daki orijinal commit main'de yok, squash commit'i var.
                "squash_commit_sha": fx.sha("soft_delete"),
            },
            "commits": ["e" * 40],
            "notes": [],
            "closes_issues": [],
            "related_issues": [
                {
                    "iid": 9,
                    "title": "KVKK denetimi: silinen kullanıcıların izi",
                    "description": "Denetçi silinen kayıtların izlenebilir olmasını istedi.",
                    "state": "opened",
                    "labels": ["kvkk"],
                    "author": _user("ayse"),
                    "web_url": f"{BASE}/{PROJECT}/-/issues/9",
                }
            ],
        },
        3: {
            "mr": {
                "iid": 3,
                "title": "Rate limit ayarlanabilir olsun",
                "description": "Ortam değişkeninden okunacak.",
                "state": "opened",
                "author": _user("mehmet"),
                "web_url": f"{BASE}/{PROJECT}/-/merge_requests/3",
                "created_at": "2026-04-01T09:00:00Z",
                "updated_at": "2026-04-01T09:00:00Z",
                "merged_at": None,
                "merge_commit_sha": None,
                "squash_commit_sha": None,
            },
            "commits": [],
            "notes": [],
            "closes_issues": [],
            "related_issues": [],
        },
        4: {
            "mr": {
                "iid": 4,
                "title": "Vazgeçilen deneme",
                "description": "",
                "state": "closed",
                "author": _user("ayse"),
                "web_url": f"{BASE}/{PROJECT}/-/merge_requests/4",
                "created_at": "2026-04-02T09:00:00Z",
                "updated_at": "2026-04-02T09:00:00Z",
            },
            "commits": [],
            "notes": [],
            "closes_issues": [],
            "related_issues": [],
        },
    }


@dataclass
class GitLabMock:
    data: dict[int, dict[str, Any]]
    per_page: int = 100
    fail_first_with: int | None = None  # ör. 429
    status_override: int | None = None
    list_queries: list[dict[str, list[str]]] = field(default_factory=list)

    def install(self, rsps: responses.RequestsMock) -> None:
        rsps.add_callback(
            responses.GET,
            re.compile(re.escape(API) + r"/merge_requests(\?.*)?$"),
            callback=self._list,
        )
        for sub in ("commits", "notes", "closes_issues", "related_issues"):
            rsps.add_callback(
                responses.GET,
                re.compile(re.escape(API) + rf"/merge_requests/(\d+)/{sub}(\?.*)?$"),
                callback=self._sub(sub),
            )

    def _list(self, request: Any) -> tuple[int, dict[str, str], str]:
        if self.status_override:
            return self.status_override, {}, json.dumps({"message": "401 Unauthorized"})
        if self.fail_first_with:
            code, self.fail_first_with = self.fail_first_with, None
            return code, {"Retry-After": "0"}, json.dumps({"message": "Too Many Requests"})
        url = urlparse(request.url)
        qs = parse_qs(url.query)
        self.list_queries.append(qs)
        items = sorted((d["mr"] for d in self.data.values()), key=lambda m: m["updated_at"])
        if "updated_after" in qs:
            after = qs["updated_after"][0].replace("+00:00", "Z")
            items = [m for m in items if m["updated_at"] > after]
        per_page = int(qs.get("per_page", [str(self.per_page)])[0])
        page = int(qs.get("page", ["1"])[0])
        chunk = items[(page - 1) * per_page : page * per_page]
        headers = {"Content-Type": "application/json"}
        if page * per_page < len(items):
            nxt = {k: v[0] for k, v in qs.items()} | {"page": str(page + 1)}
            headers["Link"] = f'<{API}/merge_requests?{urlencode(nxt)}>; rel="next"'
        return 200, headers, json.dumps(chunk)

    def _sub(self, name: str) -> Any:
        def cb(request: Any) -> tuple[int, dict[str, str], str]:
            iid = int(re.search(r"/merge_requests/(\d+)/", request.url).group(1))  # type: ignore[union-attr]
            entry = self.data[iid]
            if name == "commits":
                payload: Any = [{"id": sha} for sha in entry["commits"]]
            else:
                payload = entry[name]
            return 200, {"Content-Type": "application/json"}, json.dumps(payload)

        return cb
