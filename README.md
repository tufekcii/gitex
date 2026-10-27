# gitsor

Git geçmişini doğal dilde (Türkçe/İngilizce) sorgulayan komut satırı aracı. Cevaplar
**ne değişti, ne zaman, kim, neden** sorularını yanıtlar ve her iddiayı commit SHA'sı, tarih ve
(varsa) GitLab MR/issue linkiyle kaynaklandırır. Cevaptaki her SHA ve MR referansı indekse/git'e
karşı doğrulanır; uydurma bir referans önce modele düzelttirilir, düzelmezse `⚠ doğrulanamadı`
olarak işaretlenir.

```text
$ gitsor ask "Login'deki rate limit ne zaman eklendi?"
  → pickaxe(term='RATE_LIMIT')
  → get_commit(sha='6b1285f')
Rate limit ilk olarak 6b1285f (2026-01-20, Mehmet Demir) ile eklendi: IP başına dakikada 5
deneme. Daha sonra c17ca5f (2026-03-15, Mehmet Demir) ile 10'a çıkarıldı; commit mesajına göre
NAT arkasındaki kurumsal kullanıcılar yanlışlıkla engelleniyordu.

Kaynaklar
- 6b1285f — 2026-01-20 — Mehmet Demir — Login'e rate limit eklendi
- c17ca5f — 2026-03-15 — Mehmet Demir — Rate limit 5'ten 10'a çıkarıldı
```

## Kurulum

Python 3.12+ ve [uv](https://docs.astral.sh/uv/) gerekir; `git` PATH'te olmalıdır.

```bash
uv tool install git+https://gitlab.com/<grup>/gitsor.git   # ya da yerel kopyadan:
uv tool install .
```

## Hızlı başlangıç

```bash
cd projeniz
gitsor init      # .gitsor/config.toml oluşturur, .gitignore'a .gitsor/ ekler
gitsor index     # yerel git geçmişini indeksler (artımlı; --rebuild ile sıfırdan)
gitsor status    # indeks, son senkron ve config özeti
gitsor ask "payment/service.py son 3 ayda neden bu kadar değişti?"
```

`ask` indeks yoksa ya da eskiyse önce otomatik artımlı indeksleme yapar.

## Komutlar

| Komut | Açıklama |
|---|---|
| `gitsor init` | `.gitsor/` oluşturur, örnek config yazar, `.gitignore`'a ekler |
| `gitsor index [--rebuild]` | Yerel git indeksleme (artımlı; rebase/force-push ile kaybolan commit'leri temizler) |
| `gitsor sync [--full]` | GitLab MR, review yorumu ve issue senkronizasyonu (gerekirse önce index) |
| `gitsor ask "soru" [--path P] [--since T] [--until T] [--mode simple\|agent] [--show-context] [--json] [-q]` | Soru sor |
| `gitsor explain <sha\|!MR>` | Bir commit'i ya da MR'ı açıklar |
| `gitsor when "ifade" [--path P] [-E]` | Pickaxe ile ifadenin ne zaman eklendiği/kaldırıldığı (LLM gerekmez) |
| `gitsor file <path> [--llm]` | Dosyanın evrim özeti (LLM gerekmez; `--llm` ile anlatım eklenir) |
| `gitsor chat` | Etkileşimli oturum; takip soruları bağlamı korur (`/yeni`, `/mod`, `/json`, `/çık`) |
| `gitsor status` | İndeks durumu, son senkron, config özeti |

Genel seçenek: `-C/--repo PATH` başka bir dizindeki depoyu hedefler.

- `ask` çalışırken çağrılan araçları sade satırlarla gösterir; `--quiet` kapatır.
- `--show-context` LLM'e gidecek mesajları **göndermeden önce** ekrana basar (denetim/debug).
- `--json` makine-okunur çıktı verir: `answer`, doğrulanmış `sources`, `unverified`,
  `tool_calls`, `usage`.

### Örnek sorular

```bash
gitsor ask "Login'deki rate limit ne zaman eklendi?"
gitsor ask "payment/service.py son 3 ayda neden bu kadar değişti?"
gitsor ask "a1b2c3d commit'i ne yaptı, hangi MR ile geldi, review'da ne tartışıldı?"
gitsor ask "Kullanıcı silme davranışı ne zaman soft-delete'e döndü ve kim yaptı?"
gitsor ask "When was the debug_dump helper removed and why?"
gitsor when "check_rate_limit"
gitsor explain '!42'
```

## Yapılandırma

Config dosyaları (sonraki öncekini ezer):

1. `~/.config/gitsor/config.toml` (ya da `GITSOR_CONFIG` ile verilen yol)
2. `<repo>/.gitsor/config.toml` (öncelikli)
3. Ortam değişkenleri: `GITSOR_LLM_PROVIDER`, `GITSOR_LLM_MODEL`, `GITSOR_LLM_BASE_URL`,
   `GITSOR_LLM_MODE`, `GITSOR_GITLAB_URL`, `GITSOR_GITLAB_PROJECT`

**Sırlar dosyaya yazılmaz.** LLM anahtarı `llm.api_key_env` ile adı verilen ortam
değişkeninden (varsayılan `GITSOR_LLM_API_KEY`), GitLab token'ı `GITSOR_GITLAB_TOKEN`'dan okunur.

```toml
[llm]
provider = "openai_compat"        # veya "anthropic"
model = "qwen2.5-7b-instruct"
base_url = "http://localhost:8000/v1"
api_key_env = "GITSOR_LLM_API_KEY"
mode = "agent"                    # "agent" (tool-use) veya "simple"
max_tool_calls = 12
temperature = 0.1                 # yalnızca openai_compat'a gönderilir
# max_tokens = 4096               # boşsa sağlayıcı varsayılanı
# tool_output_chars = 8000        # tek bir araç çıktısının karakter bütçesi
# context_chars = 40000           # simple moddaki toplam bağlam bütçesi
# simple_top_n = 6                # simple modda detayı bağlama konan commit sayısı

[privacy]
send_diffs = true                 # false ise LLM'e sadece metadata + mesajlar gider
max_diff_chars = 12000
exclude_paths = ["*.env", "*.pem", "*.key", "secrets/**", "*.lock"]

[gitlab]
url = "https://gitlab.com"
project = "grup/proje"
```

### vLLM

```bash
vllm serve Qwen/Qwen2.5-7B-Instruct --enable-auto-tool-choice --tool-call-parser hermes
```

```toml
[llm]
provider = "openai_compat"
model = "Qwen/Qwen2.5-7B-Instruct"
base_url = "http://localhost:8000/v1"
mode = "agent"
```

vLLM'de tool calling için `--enable-auto-tool-choice` ve modele uygun `--tool-call-parser`
gerekir; açık değilse `mode = "simple"` kullanın.

### Ollama

```toml
[llm]
provider = "openai_compat"
model = "qwen2.5:7b"
base_url = "http://localhost:11434/v1"
mode = "simple"                   # küçük modellerde genelde daha isabetli
```

### Claude (Anthropic API)

```toml
[llm]
provider = "anthropic"
model = "claude-opus-5-5"
api_key_env = "ANTHROPIC_API_KEY"
mode = "agent"
```

Claude API'de bir istek güvenlik sınıflandırıcısınca reddedilirse sunucu tarafında yedek modele
devredilir (`llm.anthropic_fallbacks = true`, varsayılan). Kapatmak için `false` yapın.

### Modlar

- **agent**: model araçları (`search_commits`, `pickaxe`, `file_history`, `line_history`,
  `blame`, `get_commit`, `list_paths`, GitLab varsa `search_mrs`, `get_mr`) kendisi çağırır.
  Tool calling'i iyi yapan modeller için.
- **simple**: sorudan anahtar kelime, kod terimi, yol ve tarih aralığı kurallarla (gerekirse tek
  bir küçük LLM çağrısıyla) çıkarılır; arama sonuçları birleştirilip tek çağrıda cevap üretilir.
  Tool calling'de zayıf küçük modeller için.

## GitLab

`[gitlab] project` ayarlanıp `GITSOR_GITLAB_TOKEN` (`read_api` yetkili) verildiğinde
`gitsor sync` merged ve açık MR'ları, sistem dışı review yorumlarını (diff yorumlarında
dosya/satır bilgisiyle) ve MR'ın kapattığı/ilişkili issue'ları indeksler. Senkron artımlıdır
(`updated_after`), 429'da `Retry-After`'a uyar. SHA→MR eşlemesi MR commit'leri,
`merge_commit_sha` ve `squash_commit_sha` üzerinden yapılır. GitLab ayarlı değilse araç yalnızca
yerel git ile tam çalışır ve GitLab araçları modele hiç sunulmaz.

## Gizlilik

- İndeks (`.gitsor/index.db`) diff içeriği saklamaz; diff'ler ihtiyaç anında git'ten okunur.
- LLM'e giden tüm araç çıktılarında API anahtarı, token, parola, private key, JWT ve bağlantı
  dizesi kalıpları `[REDACTED]` ile maskelenir.
- `exclude_paths` ile eşleşen dosyaların diff'i hiç gönderilmez; `send_diffs = false` iken
  araçlar diff ve kod satırı döndürmez.
- `--show-context` ile gönderilecek bağlam önceden incelenebilir.

## Geliştirme

```bash
uv sync
uv run pytest                                  # ağa çıkan test yoktur
uv run ruff check . && uv run ruff format --check .
uv run mypy
```

Mimari kararlar ve bağımlılık gerekçeleri: [docs/decisions.md](docs/decisions.md).
