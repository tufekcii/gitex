"""Kullanıcıya anlamlı mesajla gösterilen hata türleri."""

from __future__ import annotations


class GitexError(Exception):
    """Tüm gitex hatalarının tabanı. `hint` kullanıcıya çözüm önerisi sunar."""

    def __init__(self, message: str, hint: str | None = None) -> None:
        super().__init__(message)
        self.hint = hint


class NotAGitRepoError(GitexError):
    pass


class GitCommandError(GitexError):
    pass


class ConfigError(GitexError):
    pass


class IndexMissingError(GitexError):
    pass


class LLMError(GitexError):
    pass


class GitLabError(GitexError):
    pass
