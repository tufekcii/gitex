# gitex

Git geçmişini doğal dilde (Türkçe/İngilizce) sorgulayan komut satırı aracı. Cevaplar
**ne değişti, ne zaman, kim, neden** sorularını yanıtlar ve her iddiayı commit SHA'sı, tarih ve
(varsa) GitLab MR/issue linkiyle kaynaklandırır. Cevaptaki her SHA ve MR referansı indekse/git'e
karşı doğrulanır; uydurma bir referans önce modele düzelttirilir, düzelmezse `⚠ doğrulanamadı`
olarak işaretlenir.

```text
$ gitex ask "Login'deki rate limit ne zaman eklendi?"
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
uv tool install git+https://gitlab.com/<grup>/gitex.git   # ya da yerel kopyadan:
uv tool install .
```

## Hızlı başlangıç

```bash
cd projeniz
gitex init      # .gitex/config.toml oluşturur, .gitignore'a .gitex/ ekler
gitex index     # yerel git geçmişini indeksler (artımlı; --rebuild ile sıfırdan)
gitex status    # indeks, son senkron ve config özeti
gitex ask "payment/service.py son 3 ayda neden bu kadar değişti?"
```

`ask` indeks yoksa ya da eskiyse önce otomatik artımlı indeksleme yapar.

## Komutlar

| Komut | Açıklama |
|---|---|
| `gitex init` | `.gitex/` oluşturur, örnek config yazar, `.gitignore`'a ekler |
| `gitex index [--rebuild]` | Yerel git indeksleme (artımlı; rebase/force-push ile kaybolan commit'leri temizler) |
| `gitex sync [--full]` | GitLab MR, review yorumu ve issue senkronizasyonu (gerekirse önce index) |
| `gitex ask "soru" [--path P] [--since T] [--until T] [--mode simple\|agent] [--show-context] [--json] [-q]` | Soru sor |
| `gitex explain <sha\|!MR>` | Bir commit'i ya da MR'ı açıklar |
| `gitex when "ifade" [--path P] [-E]` | Pickaxe ile ifadenin ne zaman eklendiği/kaldırıldığı (LLM gerekmez) |
| `gitex file <path> [--llm]` | Dosyanın evrim özeti (LLM gerekmez; `--llm` ile anlatım eklenir) |
| `gitex chat` | Etkileşimli oturum; takip soruları bağlamı korur (`/yeni`, `/mod`, `/json`, `/çık`) |
| `gitex status` | İndeks durumu, son senkron, config özeti |

Genel seçenek: `-C/--repo PATH` başka bir dizindeki depoyu hedefler.

- `ask` çalışırken çağrılan araçları sade satırlarla gösterir; `--quiet` kapatır.
- `--show-context` LLM'e gidecek mesajları **göndermeden önce** ekrana basar (denetim/debug).
- `--json` makine-okunur çıktı verir: `answer`, doğrulanmış `sources`, `unverified`,
  `tool_calls`, `usage`.

### Örnek sorular

```bash
gitex ask "Login'deki rate limit ne zaman eklendi?"
gitex ask "payment/service.py son 3 ayda neden bu kadar değişti?"
gitex ask "a1b2c3d commit'i ne yaptı, hangi MR ile geldi, review'da ne tartışıldı?"
gitex ask "Kullanıcı silme davranışı ne zaman soft-delete'e döndü ve kim yaptı?"
gitex ask "When was the debug_dump helper removed and why?"
gitex when "check_rate_limit"
gitex explain '!42'
```

## Yapılandırma

Config dosyaları (sonraki öncekini ezer):

1. `~/.config/gitex/config.toml` (ya da `GITEX_CONFIG` ile verilen yol)
2. `<repo>/.gitex/config.toml` (öncelikli)
3. Ortam değişkenleri: `GITEX_LLM_PROVIDER`, `GITEX_LLM_MODEL`, `GITEX_LLM_BASE_URL`,
   `GITEX_LLM_MODE`, `GITEX_GITLAB_URL`, `GITEX_GITLAB_PROJECT`

**Sırlar dosyaya yazılmaz.** LLM anahtarı `llm.api_key_env` ile adı verilen ortam
değişkeninden (varsayılan `GITEX_LLM_API_KEY`), GitLab token'ı `GITEX_GITLAB_TOKEN`'dan okunur.

```toml
[llm]
provider = "openai_compat"        # veya "anthropic"
model = "qwen2.5-7b-instruct"
base_url = "http://localhost:8000/v1"
api_key_env = "GITEX_LLM_API_KEY"
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

`[gitlab] project` ayarlanıp `GITEX_GITLAB_TOKEN` (`read_api` yetkili) verildiğinde
`gitex sync` merged ve açık MR'ları, sistem dışı review yorumlarını (diff yorumlarında
dosya/satır bilgisiyle) ve MR'ın kapattığı/ilişkili issue'ları indeksler. Senkron artımlıdır
(`updated_after`), 429'da `Retry-After`'a uyar. SHA→MR eşlemesi MR commit'leri,
`merge_commit_sha` ve `squash_commit_sha` üzerinden yapılır. GitLab ayarlı değilse araç yalnızca
yerel git ile tam çalışır ve GitLab araçları modele hiç sunulmaz.

## Gizlilik

- İndeks (`.gitex/index.db`) diff içeriği saklamaz; diff'ler ihtiyaç anında git'ten okunur.
- LLM'e giden tüm araç çıktılarında API anahtarı, token, parola, private key, JWT ve bağlantı
  dizesi kalıpları `[REDACTED]` ile maskelenir.
- `exclude_paths` ile eşleşen dosyaların diff'i hiç gönderilmez; `send_diffs = false` iken
  araçlar diff ve kod satırı döndürmez.
- `--show-context` ile gönderilecek bağlam önceden incelenebilir.

## Değerlendirme

`evals/` altında deterministik fixture deposu üzerinde soru-cevap çiftleri bulunur:

```bash
uv run python -m gitex.evals                                   # config'teki model
uv run python -m gitex.evals --mode simple --model qwen2.5:7b     --base-url http://localhost:11434/v1 --output rapor.json
uv run python -m gitex.evals --provider anthropic --model claude-opus-5-5 --case rename
```

Skorlayıcı her soru için beklenen SHA'ların doğrulanmış kaynak olarak geçip geçmediğini
(kaynak isabeti), doğrulanamayan referans oranını (uydurma), beklenen ifadelerin cevapta
geçmesini ve cevabı olmayan sorularda "bulamadım" doğruluğunu raporlar. Soru seti:
[evals/questions.toml](evals/questions.toml). Farklı modelleri karşılaştırmak için kullanılır.

## Geliştirme

```bash
uv sync
uv run pytest                                  # ağa çıkan test yoktur
uv run ruff check . && uv run ruff format --check .
uv run mypy
```

Mimari kararlar ve bağımlılık gerekçeleri: [docs/decisions.md](docs/decisions.md).
