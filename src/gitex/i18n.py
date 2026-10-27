"""Arayüz dili: Türkçe / English.

Her kullanıcıya görünen metin `t("Türkçe", "English")` ile iki dilde yan yana yazılır; böylece
çevirisi eksik metin olamaz. Dil sırası: `GITEX_LANG` → `ui.language` (kullanıcı config'i) →
işletim sisteminin dili. Modele giden metinler (araç çıktıları, promptlar) çevrilmez; model cevabı
zaten sorunun dilinde verir.
"""

from __future__ import annotations

import contextlib
import locale
import os
import tomllib
from typing import Any, Literal

from gitex.paths import user_config_path

Lang = Literal["tr", "en"]
LANGS: tuple[Lang, ...] = ("tr", "en")
LANG_NAMES: dict[Lang, str] = {"tr": "Türkçe", "en": "English"}

_current: Lang | None = None


def _normalize(value: object) -> Lang | None:
    text = str(value or "").strip().lower()
    if text.startswith(("tr", "turkish", "türk")):
        return "tr"
    if text.startswith(("en", "english")):
        return "en"
    return None


def system_language() -> Lang:
    """İşletim sisteminin dili; Türkçe değilse İngilizce."""
    candidates: list[object] = [os.environ.get(v) for v in ("LC_ALL", "LC_MESSAGES", "LANG")]
    with contextlib.suppress(ValueError):
        candidates.append(locale.getlocale()[0])
    for value in candidates:
        if value and _normalize(value) == "tr":
            return "tr"
    return "en"


def configured_language() -> Lang | None:
    path = user_config_path()
    if not path.is_file():
        return None
    try:
        with path.open("rb") as fh:
            data = tomllib.load(fh)
    except (OSError, tomllib.TOMLDecodeError):
        return None
    ui = data.get("ui")
    return _normalize(ui.get("language")) if isinstance(ui, dict) else None


def current() -> Lang:
    global _current
    if _current is None:
        _current = (
            _normalize(os.environ.get("GITEX_LANG")) or configured_language() or system_language()
        )
    return _current


def set_language(lang: Lang) -> None:
    global _current
    _current = lang
    apply_to_typer()


def reset() -> None:
    """Önbelleği temizler (testler ve dil değişikliği sonrası için)."""
    global _current
    _current = None


def t(tr: str, en: str, /, **values: Any) -> str:
    text = tr if current() == "tr" else en
    return text.format(**values) if values else text


def apply_to_typer() -> None:
    """Typer'ın kendi panel başlıklarını seçilen dile çevirir."""
    try:
        import typer.rich_utils as ru
    except ImportError:  # pragma: no cover
        return
    tr = current() == "tr"
    ru.OPTIONS_PANEL_TITLE = "Seçenekler" if tr else "Options"
    ru.COMMANDS_PANEL_TITLE = "Komutlar" if tr else "Commands"
    ru.ARGUMENTS_PANEL_TITLE = "Argümanlar" if tr else "Arguments"
    ru.ERRORS_PANEL_TITLE = "Hata" if tr else "Error"
    ru.ABORTED_TEXT = "İptal edildi." if tr else "Aborted."
    ru.DEFAULT_STRING = "[varsayılan: {}]" if tr else "[default: {}]"
    ru.REQUIRED_LONG_STRING = "[zorunlu]" if tr else "[required]"
