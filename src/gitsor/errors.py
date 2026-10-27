"""Kullanıcıya anlamlı mesajla gösterilen hata türleri."""

from __future__ import annotations


class GitsorError(Exception):
    """Tüm gitsor hatalarının tabanı. `hint` kullanıcıya çözüm önerisi sunar."""

    def __init__(self, message: str, hint: str | None = None) -> None:
        super().__init__(message)
        self.hint = hint


class NotAGitRepoError(GitsorError):
    pass


class GitCommandError(GitsorError):
    pass


class ConfigError(GitsorError):
    pass


class IndexMissingError(GitsorError):
    pass


class LLMError(GitsorError):
    pass


class GitLabError(GitsorError):
    pass
