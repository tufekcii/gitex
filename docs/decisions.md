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
- 2026-10-27 — Bağımlılık: `openai` — OpenAI uyumlu uç noktalar (vLLM, Ollama, OpenAI) için resmi SDK; `base_url` ile hepsine çalışır.
- 2026-10-27 — Bağımlılık: `anthropic` — Claude API native tool use için resmi SDK.
- 2026-10-27 — Anthropic adaptörüne `temperature` gönderilmez (güncel Claude API örnekleme parametrelerini 400 ile reddediyor); `tool_choice` gönderilmez (zorlanmış seçim güncel modellerde desteklenmiyor). Varsayılan model `claude-opus-5-5`, `max_tokens` 16000.
- 2026-10-27 — Anthropic yanıtının ham içerik blokları (thinking dahil) asistan mesajında saklanıp aynen geri gönderilir; geçmişte tool_use varken her çağrıda araç tanımları da gönderilir.
- 2026-10-27 — Claude API'de (özel base_url yoksa) sunucu tarafı reddetme yedeği (`fallbacks: "default"`, beta `server-side-fallback-2026-07-01`) varsayılan açık; `llm.anthropic_fallbacks = false` ile kapanır.
- 2026-10-27 — Araç çıktıları sade metin (JSON değil): küçük modeller için daha az token ve daha kolay okunur. Tüm araç çıktıları LLM'e gitmeden `redact()`'ten geçer.
- 2026-10-27 — `redact` tırnaksız değerlerde yalnızca anahtara benzeyenleri (>=16 karakter ya da rakam içeren >=8) maskeler; `token = tokenize(...)`, `settings.SECRET_KEY` gibi kod dokunulmaz.
- 2026-10-27 — Kaynak doğrulama: SHA = 7-40 hex ve en az bir rakam ("defaced" gibi kelimeleri dışlar). GitLab yoksa her MR referansı doğrulanamaz sayılır.
- 2026-10-27 — `when` ve `file` LLM gerektirmeyen deterministik çıktılar üretir (`file --llm` ile anlatım eklenir); `ask/explain` ortak `Session` katmanını kullanır.
- 2026-10-27 — Simple modda LLM parametre çıkarımı yalnızca kurallar kod terimi/yol/SHA/MR bulamazsa yapılır (en fazla bir ek çağrı).
- 2026-10-27 — Bağımlılık: `python-gitlab` — spec gereği; sayfalama ve 429 (`Retry-After`) geri çekilmesini kendisi yönetir, `gitlab.max_retries` ile sınırlanır.
- 2026-10-27 — Test bağımlılığı: `responses` — python-gitlab'ın `requests` çağrılarını ağa çıkmadan mock'lar.
- 2026-10-27 — MR'lar `state=all` ile çekilir; yalnızca `merged`/`opened` saklanır, kapatılan (merge edilmemiş) MR'lar artımlı senkronda indeksten silinir.
- 2026-10-27 — Senkron imleci (`gitlab_last_sync`) istek başlamadan alınan zamandır; senkron sırasında güncellenenler bir sonraki turda tekrar gelir (idempotent yazım).
- 2026-10-27 — `gitlab.project` değişirse GitLab verisi sıfırdan senkronlanır.
- 2026-10-27 — SHA→MR eşlemesi: MR commit listesi + `merge_commit_sha` + `squash_commit_sha`. Rebase ile merge edilen MR'larda main'deki SHA'lar MR listesindekilerden farklı olabilir; bu durumda eşleme yalnızca merge/squash commit'i üzerinden yapılabilir (bilinen sınırlama).
- 2026-10-27 — chat geçmişi büyüyünce yerinde budanmaz; son turların özetiyle yeni konuşma açılır (bazı sağlayıcılar düzenlenmiş geçmişi reddeder). Simple mod durumsuz olduğundan takip sorularına son 3 tur metin olarak eklenir.
