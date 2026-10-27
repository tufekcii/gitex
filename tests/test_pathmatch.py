import pytest

from gitsor.git.pathmatch import match_path


@pytest.mark.parametrize(
    ("path", "pattern", "expected"),
    [
        ("config/prod.env", "*.env", True),
        (".env", "*.env", True),
        ("secrets/a/b.txt", "secrets/**", True),
        ("app/secrets/x", "secrets/**", False),
        ("uv.lock", "*.lock", True),
        ("payment/service.py", "payment/*.py", True),
        ("payment/sub/service.py", "payment/*.py", False),
        ("payment/sub/service.py", "payment/**/*.py", True),
        ("a/b/c.pem", "**/*.pem", True),
        ("docs/x.md", "docs/", True),
    ],
)
def test_match_path(path: str, pattern: str, expected: bool) -> None:
    assert match_path(path, pattern) is expected
