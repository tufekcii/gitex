from __future__ import annotations

import pytest

from gitsor.redact import MASK, redact

# Sahte değerler parça parça kurulur; kaynakta gerçek bir anahtar kalıbı durmaz.
AWS = "AKIA" + "ABCDEFGHIJKLMNOP"
GITLAB = "glpat-" + "x" * 20
GITHUB = "ghp_" + "a1" * 15
JWT = "eyJ" + "hbGciOiJIUzI1" + ".eyJ" + "zdWIiOiIxMjM0" + "." + "SflKxwRJSMeKKF2QT4"
PEM = "-----BEGIN RSA PRIVATE KEY-----\nMIIEow" + "IBAAKCAQEA\n-----END RSA PRIVATE KEY-----"


@pytest.mark.parametrize(
    ("raw", "leak"),
    [
        (f"key={AWS}", AWS),
        (f"token: {GITLAB}", GITLAB),
        (f"export GH={GITHUB}", GITHUB),
        (f"Authorization: Bearer {JWT}", JWT),
        (PEM, "MIIEowIBAAKCAQEA"),
        ("DATABASE_URL=postgres://app:hunter2pass@db:5432/x", "hunter2pass"),
        ('password = "correct horse"', "correct horse"),
        ("api_key: 'abcd1234efgh'", "abcd1234efgh"),
        ("SECRET_TOKEN=s3cr3tvalue99", "s3cr3tvalue99"),
        ("client_secret=ZXhhbXBsZXNlY3JldHZhbHVl", "ZXhhbXBsZXNlY3JldHZhbHVl"),
        ("+    OPENAI = 'sk-" + "proj" + "-abcdefghijklmnop1234'", "abcdefghijklmnop1234"),
    ],
)
def test_secrets_are_masked(raw: str, leak: str) -> None:
    out = redact(raw)
    assert leak not in out
    assert MASK in out


@pytest.mark.parametrize(
    "code",
    [
        "def login(username: str, password: str) -> bool:",
        "tokens = tokenize(text)",
        "if not check_rate_limit(ip):",
        "token = os.environ['TOKEN']",
        "password = None",
        "secret_key = settings.SECRET_KEY",
    ],
)
def test_code_is_not_masked(code: str) -> None:
    assert redact(code) == code


def test_empty() -> None:
    assert redact("") == ""
