"""LLM'e gitmeden önce metindeki gizli bilgileri maskeler.

Kalıplar bilinçli olarak geniş tutulur: yanlış pozitif (gereksiz maskeleme) bir sızıntıdan
her zaman daha ucuzdur.
"""

from __future__ import annotations

import re

MASK = "[REDACTED]"

_PRIVATE_KEY = re.compile(
    r"-----BEGIN [A-Z0-9 ]*PRIVATE KEY-----.*?(?:-----END [A-Z0-9 ]*PRIVATE KEY-----|\Z)",
    re.DOTALL,
)

# Bağımsız token biçimleri (tamamı maskelenir).
_TOKEN_PATTERNS = [
    re.compile(r"\bAKIA[0-9A-Z]{16}\b"),  # AWS erişim anahtarı
    re.compile(
        r"\b(?:sk|pk|rk)[-_](?:live|test|proj|ant)?[-_]?[A-Za-z0-9_\-]{16,}"
    ),  # OpenAI/Stripe/Anthropic
    re.compile(r"\bgh[pousr]_[A-Za-z0-9]{20,}\b"),  # GitHub
    re.compile(r"\bglpat-[A-Za-z0-9_\-]{20,}\b"),  # GitLab PAT
    re.compile(
        r"\bgl(?:dt|rt|cbt|ptt|ft|imt|agent)-[A-Za-z0-9_\-]{16,}\b"
    ),  # diğer GitLab token'ları
    re.compile(r"\bxox[abprs]-[A-Za-z0-9\-]{10,}\b"),  # Slack
    re.compile(r"\bAIza[0-9A-Za-z_\-]{35}\b"),  # Google API
    re.compile(r"\beyJ[A-Za-z0-9_\-]{8,}\.eyJ[A-Za-z0-9_\-]{8,}\.[A-Za-z0-9_\-]{8,}"),  # JWT
    re.compile(r"\bhf_[A-Za-z0-9]{30,}\b"),  # Hugging Face
]

# scheme://kullanıcı:PAROLA@host  ->  parola maskelenir.
_CONN_STRING = re.compile(
    r"(?P<pre>\b[a-zA-Z][a-zA-Z0-9+.\-]*://[^:/\s@]+:)(?P<secret>[^@\s/]+)(?P<post>@)"
)

# Authorization: Bearer xxx / Basic xxx
_AUTH_HEADER = re.compile(
    r"(?i)(?P<pre>\b(?:authorization|proxy-authorization)\s*[:=]\s*[\"']?(?:bearer|basic|token)\s+)(?P<secret>[A-Za-z0-9._~+/=\-]{8,})"
)

# anahtar = "değer" atamaları (password, secret, token, api_key ...)
_ASSIGNMENT = re.compile(
    r"(?ix)"
    r"(?P<pre>\b[\w.\-]*(?:passw(?:or)?d|passwd|pwd|parola|sifre|şifre|secret|token|api[_\-]?key"
    r"|access[_\-]?key|private[_\-]?key|client[_\-]?secret|auth[_\-]?key|credentials?)[\w.\-]*"
    r"[\"']?\s*(?::=|=>|=|:)\s*[\"']?)"
    r"(?P<secret>[^\s\"',;()\[\]{}]{4,})"
)


def _mask_group(match: re.Match[str]) -> str:
    return f"{match.group('pre')}{MASK}{match.groupdict().get('post') or ''}"


def redact(text: str) -> str:
    if not text:
        return text
    text = _PRIVATE_KEY.sub(MASK, text)
    for pattern in _TOKEN_PATTERNS:
        text = pattern.sub(MASK, text)
    text = _CONN_STRING.sub(_mask_group, text)
    text = _AUTH_HEADER.sub(_mask_group, text)
    text = _ASSIGNMENT.sub(_assignment_sub, text)
    return text


def _assignment_sub(match: re.Match[str]) -> str:
    secret = match.group("secret")
    # Zaten maskelenmiş, değişken referansı ya da açıkça yer tutucu olan değerleri bırak.
    if secret.startswith(("[REDACTED", "$", "{{", "<", "os.environ", "env(", "getenv")):
        return match.group(0)
    if secret.lower() in {"none", "null", "true", "false", "required", "optional"}:
        return match.group(0)
    quoted = match.group("pre").rstrip().endswith(("'", '"'))
    # `settings.SECRET_KEY`, `DEFAULT_TOKEN` gibi tırnaksız referanslar koddur.
    if not quoted and re.fullmatch(r"[A-Za-z_][\w.]*", secret) and ("." in secret or "_" in secret):
        return match.group(0)
    # Tırnaksız değerler kod olabilir (`token = tokenize`, `password: str`): yalnızca
    # anahtara benzeyenleri (rakam içeren >=8 karakter ya da >=16 karakter) maskele.
    if not quoted and not (
        len(secret) >= 16 or (len(secret) >= 8 and any(c.isdigit() for c in secret))
    ):
        return match.group(0)
    return f"{match.group('pre')}{MASK}"
