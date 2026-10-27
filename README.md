# gitsor

Git geçmişini doğal dilde (Türkçe/İngilizce) sorgulayan komut satırı aracı.

## Hızlı başlangıç

```bash
cd projeniz
gitsor init        # .gitsor/config.toml oluşturur, .gitignore'a ekler
gitsor index       # yerel git geçmişini indeksler (artımlı; --rebuild ile sıfırdan)
gitsor status      # indeks ve config özeti
```

Soru sorma (LLM gerekir, aşağıdaki config'e bakın):

```bash
gitsor ask "Login'deki rate limit ne zaman eklendi?"
gitsor ask "payment/service.py son 3 ayda neden bu kadar değişti?" --mode simple
gitsor ask "Kullanıcı silme ne zaman soft-delete'e döndü?" --json
gitsor explain a1b2c3d             # bir commit'i açıklar
gitsor when "debug_dump"           # pickaxe: ne zaman eklendi/kaldırıldı (LLM gerekmez)
gitsor file payment/service.py     # dosyanın evrim özeti (LLM gerekmez; --llm ile anlatım)
```

`ask` hangi araçların çağrıldığını gösterir (`--quiet` ile kapanır); `--show-context` LLM'e
gidecek bağlamı göndermeden önce ekrana basar.

GitLab (opsiyonel): `.gitsor/config.toml` içinde `[gitlab] project = "grup/proje"` ayarlayıp
`read_api` yetkili token'ı ortam değişkeniyle verin; sonra `gitsor sync` MR'ları, review
yorumlarını ve bağlı issue'ları indeksler (artımlı; `--full` ile sıfırdan). GitLab ayarlı değilse
araç yalnızca yerel git ile tam çalışır.

İndeks repo başına `.gitsor/index.db` (SQLite + FTS5) dosyasındadır. Diff içerikleri indekse
yazılmaz; ihtiyaç anında git'ten okunur.

## Geliştirme

```bash
uv sync
uv run gitsor --help
uv run pytest
uv run ruff check . && uv run ruff format --check . && uv run mypy
```
