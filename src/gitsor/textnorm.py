"""Türkçe/İngilizce metin normalizasyonu ve FTS sorgu üretimi."""

from __future__ import annotations

import re
import unicodedata

_TR_MAP = str.maketrans({"ı": "i", "İ": "i", "I": "i"})

# Soru kalıplarında anlam taşımayan kelimeler (katlanmış hâlde).
_STOPWORDS_TEXT = """
ne zaman neden nicin niye kim kimin nasil hangi hangisi bu su o bir ve veya ile icin mi mu
de da ki gibi daha cok en son ilk olan oldu yapti yapildi degisti degistirdi eklendi kaldirildi
commit commiti committe dosya dosyasi kod satir mr merge request repo icinde ait ilgili var yok
the a an and or of in on at to for with by from is was were be been what when why who which how
did does do this that it its changed added removed file code
"""
STOPWORDS = frozenset(_STOPWORDS_TEXT.split())

_WORD_RE = re.compile(r"[\w\-']+", re.UNICODE)


def fold(text: str) -> str:
    """Küçük harfe çevirir, Türkçe noktasız/noktalı i'yi ve aksanları sadeleştirir."""
    lowered = text.translate(_TR_MAP).lower()
    decomposed = unicodedata.normalize("NFKD", lowered)
    return "".join(c for c in decomposed if not unicodedata.combining(c))


def tokens(text: str, *, drop_stopwords: bool = True) -> list[str]:
    out: list[str] = []
    for raw in _WORD_RE.findall(fold(text)):
        for part in re.split(r"['\-]", raw):
            if len(part) < 2:
                continue
            if drop_stopwords and part in STOPWORDS:
                continue
            if part not in out:
                out.append(part)
    return out


# Katlanmış hâlde yaygın Türkçe çekim ekleri (uzundan kısaya). Sorgu önek eşleşmesi
# (`kok*`) kullandığı için fazla kırpmak yalnızca biraz gürültü ekler, eşleşmeyi kaçırmaz.
_SUFFIXES = (
    "lerin", "larin", "leri", "lari", "ler", "lar", "nin", "nun", "den", "dan", "ten",
    "tan", "de", "da", "te", "ta", "yi", "yu", "ye", "ya", "si", "su", "in", "un",
    "i", "u", "e", "a",
)  # fmt: skip
_MIN_STEM = 4


def _stem(token: str) -> str:
    """Kaba Türkçe kök bulma: en fazla iki ek kırpılır, kök en az 4 harf kalır."""
    if token.isdigit():
        return token
    stem = token
    for _ in range(2):
        for suf in _SUFFIXES:
            if stem.endswith(suf) and len(stem) - len(suf) >= _MIN_STEM:
                stem = stem[: -len(suf)]
                break
        else:
            break
    return stem


def fts_query(text: str) -> str | None:
    """Serbest metni güvenli bir FTS5 MATCH ifadesine çevirir (OR'lu önek terimler)."""
    terms = tokens(text)
    if not terms:
        terms = tokens(text, drop_stopwords=False)
    if not terms:
        return None
    parts = []
    for t in terms:
        safe = t.replace('"', "")
        if not safe:
            continue
        parts.append(f'"{_stem(safe)}"*')
    return " OR ".join(parts) if parts else None
