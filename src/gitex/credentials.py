"""Gizli anahtarların işletim sisteminin anahtar kasasında saklanması.

Windows Credential Manager, macOS Keychain ya da Linux Secret Service (`keyring`). Sırlar hiçbir
zaman config dosyasına yazılmaz. Okuma sırası her zaman: ortam değişkeni → anahtar kasası.
"""

from __future__ import annotations

from urllib.parse import urlparse

from gitex.errors import GitexError
from gitex.i18n import t

SERVICE = "gitex"


def llm_key_name(provider: str, base_url: str | None) -> str:
    """LLM anahtarının kasadaki adı; aynı sağlayıcının farklı uç noktaları ayrı tutulur."""
    host = urlparse(base_url).netloc if base_url else ""
    return f"llm:{provider}" + (f"@{host}" if host else "")


def gitlab_key_name(url: str) -> str:
    return f"gitlab:{urlparse(url).netloc or url}"


def backend_name() -> str | None:
    """Kullanılabilir bir kasa varsa adını, yoksa None döner."""
    try:
        import keyring
        from keyring.backends import fail

        kr = keyring.get_keyring()
        if isinstance(kr, fail.Keyring):
            return None
        return type(kr).__name__
    except Exception:
        return None


def get_secret(name: str) -> str | None:
    """Kasadaki değeri döner; kasa yoksa ya da hata olursa sessizce None (env'e düşülür)."""
    try:
        import keyring

        value = keyring.get_password(SERVICE, name)
    except Exception:
        return None
    return value or None


def set_secret(name: str, value: str) -> None:
    try:
        import keyring

        keyring.set_password(SERVICE, name, value)
    except Exception as exc:
        raise GitexError(
            t("Anahtar kasasına yazılamadı: {e}", "Could not write to the keychain: {e}", e=exc),
            hint=t(
                "Bu sistemde anahtar kasası yoksa değeri ortam değişkeniyle verin (bkz. `gitex auth status`).",
                "If this system has no keychain, provide the value via an environment variable (see `gitex auth status`).",
            ),
        ) from exc


def delete_secret(name: str) -> bool:
    """Silindiyse True, zaten yoksa False."""
    try:
        import keyring
        from keyring.errors import PasswordDeleteError

        try:
            keyring.delete_password(SERVICE, name)
        except PasswordDeleteError:
            return False
    except GitexError:
        raise
    except Exception as exc:
        raise GitexError(
            t(
                "Anahtar kasasından silinemedi: {e}",
                "Could not remove from the keychain: {e}",
                e=exc,
            )
        ) from exc
    return True


def mask(value: str | None) -> str:
    if not value:
        return "-"
    return value[:4] + "…" + value[-4:] if len(value) > 12 else "****"
