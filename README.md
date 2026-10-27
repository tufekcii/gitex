# gitsor

Git geçmişini doğal dilde (Türkçe/İngilizce) sorgulayan komut satırı aracı.

## Hızlı başlangıç

```bash
cd projeniz
gitsor init        # .gitsor/config.toml oluşturur, .gitignore'a ekler
gitsor index       # yerel git geçmişini indeksler (artımlı; --rebuild ile sıfırdan)
gitsor status      # indeks ve config özeti
```

İndeks repo başına `.gitsor/index.db` (SQLite + FTS5) dosyasındadır. Diff içerikleri indekse
yazılmaz; ihtiyaç anında git'ten okunur.

## Geliştirme

```bash
uv sync
uv run gitsor --help
uv run pytest
uv run ruff check . && uv run ruff format --check . && uv run mypy
```
