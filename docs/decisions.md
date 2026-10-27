# Kararlar

Her satır: tarih — karar — gerekçe.

- 2026-10-27 — Build backend olarak `hatchling` — uv ile sorunsuz, src layout'u tek satırla destekler.
- 2026-10-27 — Bağımlılık: `typer`, `rich` — spec gereği CLI ve renkli çıktı.
- 2026-10-27 — Bağımlılık: `pydantic` — config doğrulaması (spec gereği).
- 2026-10-27 — Geliştirme: `pytest`, `ruff`, `mypy` — spec gereği test/lint/tip denetimi.
- 2026-10-27 — mypy `strict = true`; testlerde yalnızca tip anotasyonu zorunluluğu gevşetildi.
- 2026-10-27 — FTS5 tabloları içerik saklayan normal tablolar; metin `fold()` ile (küçük harf, `ı/İ→i`, aksan silme) yazılır — `unicode61 remove_diacritics 2` noktasız ı'yı i'ye katlamıyor (`kullanıcı`/`kullanici`).
- 2026-10-27 — FTS sorgusu: stopword ayıklanmış terimler, kaba Türkçe ek kırpma + önek eşleşmesi (`odem*`), OR ile birleşir ve bm25 ile sıralanır — morfolojik analizör bağımlılığı olmadan makul geri çağırma.
- 2026-10-27 — İndeks `--all` (stash hariç) ile tüm dalları/tag'leri kapsar; artımlılık "bilinen SHA kümesi" farkıyla yapılır, böylece rebase/force-push ile erişilemez olan commit'ler de tespit edilip silinir. Tazelik kontrolü ref parmak izi ile.
- 2026-10-27 — Merge commit'lerin dosya değişiklikleri ilk parent'a göre (`--diff-merges=first-parent`) — merge'in hedef dala getirdiği değişikliği gösterir.
- 2026-10-27 — Filtrelerde tarih olarak author date kullanılır (cevaplarda gösterilen tarih ile tutarlı).
- 2026-10-27 — Fixture deposu paket içinde (`gitsor.evals.fixture`): testler ve Faz 5 değerlendirmesi aynı deterministik depoyu kullanır.
