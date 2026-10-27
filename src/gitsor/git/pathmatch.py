"""Gitignore benzeri glob eşleştirme (`*`, `?`, `**`)."""

from __future__ import annotations

import re
from collections.abc import Iterable
from functools import lru_cache


@lru_cache(maxsize=256)
def _compile(pattern: str) -> re.Pattern[str]:
    anchored = "/" in pattern.rstrip("/")
    pat = pattern.lstrip("/")
    if pat.endswith("/"):
        pat += "**"
    out: list[str] = []
    i = 0
    while i < len(pat):
        ch = pat[i]
        if pat.startswith("**/", i):
            out.append("(?:.*/)?")
            i += 3
        elif pat.startswith("**", i):
            out.append(".*")
            i += 2
        elif ch == "*":
            out.append("[^/]*")
            i += 1
        elif ch == "?":
            out.append("[^/]")
            i += 1
        else:
            out.append(re.escape(ch))
            i += 1
    body = "".join(out)
    # Eğik çizgi içermeyen kalıplar (ör. `*.env`) her dizinde dosya adına uyar.
    prefix = "" if anchored else "(?:.*/)?"
    return re.compile(f"^{prefix}{body}(?:/.*)?$")


def match_path(path: str, pattern: str) -> bool:
    return _compile(pattern).match(path.replace("\\", "/")) is not None


def match_any(path: str, patterns: Iterable[str]) -> bool:
    return any(match_path(path, p) for p in patterns)


def has_glob(pattern: str) -> bool:
    return any(c in pattern for c in "*?[")
