<div align="center">

<picture>
  <source media="(prefers-color-scheme: dark)" srcset="docs/assets/logo-dark.svg">
  <img src="docs/assets/logo-light.svg" alt="gitex" width="260">
</picture>

### Git geçmişine her şeyi sorun — cevaplar kanıtıyla gelsin.

**gitex**, *ne değişti, ne zaman, kim yaptı ve neden* sorularını Türkçe ya da İngilizce yanıtlayan
bir komut satırı aracıdır. Her iddia bir commit SHA'sı, tarih ve varsa arkasındaki GitLab merge
request'i ve issue'su ile desteklenir. Her referans size ulaşmadan önce doğrulanır.

[![Python 3.12+](https://img.shields.io/badge/python-3.12%2B-3776AB?logo=python&logoColor=white)](https://www.python.org/)
[![uv](https://img.shields.io/badge/packaged%20with-uv-DE5FE9?logo=astral&logoColor=white)](https://docs.astral.sh/uv/)
[![Ruff](https://img.shields.io/badge/lint-ruff-D7FF64?logo=ruff&logoColor=black)](https://docs.astral.sh/ruff/)
[![mypy strict](https://img.shields.io/badge/types-mypy%20strict-2A6DB2)](https://mypy-lang.org/)
[![Lisans: MIT](https://img.shields.io/badge/license-MIT-22C55E)](LICENSE)

[Hızlı başlangıç](#hizli-baslangic) ·
[Özellikler](#ozellikler) ·
[Nasıl çalışır](#nasil-calisir) ·
[Yapılandırma](#yapilandirma) ·
[Değerlendirme](#degerlendirme) ·
[English](README.md)

<br>

<img src="docs/assets/demo.svg" alt="gitex, rate limit sorusunu doğrulanmış commit kaynaklarıyla yanıtlıyor" width="820">

<sub>Test paketindeki örnek depo üzerinde temsilî bir oturum.</sub>

</div>

---

## Neden gitex?

Cevaplar zaten `git log`, `git blame` ve `git log -S` içinde — ama yalnızca hangi komutu, hangi
yolda, hangi metinle çalıştıracağınızı biliyorsanız. Review bağlamı ise bambaşka bir yerde: merge
request'lerde ve issue'larda.

gitex bu araçların önüne bir LLM koyar ve onu dürüst tutar:

- **Bir mühendis gibi arar.** "X ne zaman eklendi" için pickaxe, "bu satırlar nasıl değişti" için
  satır geçmişi, "buna en son kim dokundu" için blame, konular için tam metin arama.
- **Her şeyi kaynaklandırır.** Her olgusal iddia için kısa SHA, tarih ve yazar; GitLab ayarlıysa
  `!MR` linkleri.
- **Uydurmaz.** Cevaptaki her SHA ve MR indekse karşı doğrulanır. Uydurma bir referans bir kez
  düzeltilmek üzere modele geri gönderilir; yine düzelmezse `⚠ doğrulanamadı` olarak işaretlenir.
- **Kodunuzun çalıştığı yerde çalışır.** vLLM ya da Ollama ile yerel modeller veya Anthropic API
  üzerinden Claude. Geçmiş diskte indekslenir; diff'ler asla saklanmaz.

<a id="ozellikler"></a>

## ✨ Özellikler

<table>
<tr>
<td width="50%" valign="top">

**🔎 Git'e özgü arama**<br>
Pickaxe (`-S` / `-G`), satır aralığı geçmişi (`-L`), blame, yeniden adlandırmaları izleyen dosya
geçmişi, bir commit'i içeren tag ve branch'ler. Merge'ler ve boş depolar doğru ele alınır.

</td>
<td width="50%" valign="top">

**🧾 Doğrulanmış kaynaklar**<br>
Cevaptaki her SHA ve `!MR` indekse ve git'e karşı çözülür. Doğrulanamayan referans bir düzeltme
turu, ardından açık bir uyarı tetikler.

</td>
</tr>
<tr>
<td valign="top">

**🌍 Baştan iki dilli**<br>
Soru hangi dildeyse cevap o dilde. Arama Türkçe karakterleri katlar (`ödeme` ↔ `odeme`,
`kullanıcı` ↔ `kullanici`) ve yaygın ekleri kırpar.

</td>
<td valign="top">

**🦊 GitLab bağlamı**<br>
Merge request'ler, dosya ve satır bilgisiyle review yorumları, kapatılan ya da ilişkili issue'lar.
Artımlı senkron; squash ve merge commit'leri MR'larına eşlenir.

</td>
</tr>
<tr>
<td valign="top">

**🧠 Her model, iki mod**<br>
`agent` modu yetenekli modellerin araçları serbestçe çağırmasına izin verir. `simple` modu sabit
arama ve tek çağrı yapar; küçük yerel modeller de kaynaklı cevap verir.

</td>
<td valign="top">

**🔐 Varsayılan olarak gizli**<br>
API anahtarı, token, parola, private key, JWT ve bağlantı dizeleri gönderilmeden önce maskelenir.
Hariç tutulan yollar makinenizden çıkmaz; diff gönderimi tamamen kapatılabilir.

</td>
</tr>
<tr>
<td valign="top">

**⚡ Hızlı, artımlı indeks**<br>
Depo başına SQLite + FTS5. Yalnızca yeni commit'ler indekslenir; rebase ya da force-push ile
yeniden yazılan geçmiş tespit edilip temizlenir.

</td>
<td valign="top">

**📏 Ölçülebilir**<br>
Paketle gelen değerlendirme seti kaynak isabetini ve uydurma oranını puanlar; modelleri aynı
sorularda karşılaştırabilirsiniz.

</td>
</tr>
</table>

<a id="hizli-baslangic"></a>

## 🚀 Hızlı başlangıç

**Gereksinimler:** Python 3.12+, [uv](https://docs.astral.sh/uv/) ve `PATH`'te `git`.

```bash
# CLI'ı kurun (bu deponun bir kopyasından)
uv tool install .

# Herhangi bir git deposunun içinde
gitex init        # .gitex/config.toml oluşturur, .gitex/'i .gitignore'a ekler
gitex index       # yerel indeksi kurar (sonrasında artımlı)
gitex ask "Login'deki rate limit ne zaman eklendi?"
```

Soru sormadan önce gitex'i bir modele yönlendirin — bkz. [Model sağlayıcıları](#model-saglayicilari).
`ask`, indeks yoksa ya da eskiyse onu otomatik günceller.

## 💬 Kullanım

### Her şeyi sorun

```bash
gitex ask "payment/service.py son 3 ayda neden bu kadar değişti?"
gitex ask "a1b2c3d commit'i ne yaptı, hangi MR ile geldi, review'da ne tartışıldı?"
gitex ask "Kullanıcı silme davranışı ne zaman soft-delete'e döndü ve kim yaptı?"
gitex ask "When was rate limiting added to login?"          # İngilizce de olur
```

Aramayı daraltın, stratejiyi değiştirin ya da gönderileni denetleyin:

```bash
gitex ask "..." --path payment/ --since 2026-01-01 --until 2026-03-31
gitex ask "..." --mode simple          # sabit arama + tek çağrı, küçük modeller için
gitex ask "..." --show-context         # LLM'e gidecek her şeyi göndermeden önce bas
gitex ask "..." --json                 # cevap + doğrulanmış kaynaklar, makine-okunur
```

### Komutlar

| Komut | Ne yapar | LLM gerekir |
|---|---|:---:|
| `gitex init` | `.gitex/config.toml` oluşturur, `.gitex/`'i `.gitignore`'a ekler | — |
| `gitex index [--rebuild]` | Yerel git geçmişini artımlı indeksler | — |
| `gitex sync [--full]` | GitLab merge request, review yorumu ve issue senkronu | — |
| `gitex ask "soru"` | Soruyu kaynaklarıyla yanıtlar | ✓ |
| `gitex explain <sha \| !MR>` | Bir commit'i ya da merge request'i açıklar | ✓ |
| `gitex when "ifade"` | Bir ifadenin ne zaman eklendiği/kaldırıldığı (pickaxe) | — |
| `gitex file <yol> [--llm]` | Dosyanın evrimi: yazarlar, yeniden adlandırmalar, aktivite | opsiyonel |
| `gitex chat` | Takip sorularında bağlamı koruyan etkileşimli oturum | ✓ |
| `gitex status` | İndeks durumu, son senkron ve config özeti | — |

Genel seçenek: `-C, --repo YOL` başka bir dizindeki depoyu hedefler.

<details>
<summary><b>Örnek: LLM olmadan <code>gitex when</code></b></summary>

```text
$ gitex when "debug_dump"
                                         'debug_dump' geçmişi
┌────────────┬─────────┬──────────────┬────────────────────┬─────────────────────────────────────┬────┐
│ Tarih      │ SHA     │ Yazar        │ Ne oldu            │ Konu                                │ MR │
├────────────┼─────────┼──────────────┼────────────────────┼─────────────────────────────────────┼────┤
│ 2026-02-10 │ c9ea76b │ Mehmet Demir │ eklendi (+1/-0)    │ Geçici debug_dump fonksiyonu        │    │
│            │         │              │                    │ eklendi                             │    │
│ 2026-02-20 │ 7121f8f │ Mehmet Demir │ kaldırıldı (+0/-1) │ debug_dump kaldırıldı               │    │
└────────────┴─────────┴──────────────┴────────────────────┴─────────────────────────────────────┴────┘
İlk ortaya çıkış: c9ea76b 2026-02-10 Mehmet Demir — Geçici debug_dump fonksiyonu eklendi
Son durum: 7121f8f 2026-02-20 ile kaldırıldı.
```

</details>

<details>
<summary><b>Chat komutları</b></summary>

| Komut | Etkisi |
|---|---|
| `/yeni` | Yeni bir konuşma başlatır |
| `/mod agent` · `/mod simple` | Oturum ortasında mod değiştirir |
| `/json` | Son cevabı kaynaklarıyla JSON olarak basar |
| `/çık` · `Ctrl+D` | Çıkış |

</details>

<a id="nasil-calisir"></a>

## 🧭 Nasıl çalışır

```mermaid
flowchart LR
    Q([Soru]) --> M{Mod}
    M -- agent --> L[Araçlı LLM]
    M -- simple --> R[Kurallı plan<br/>+ sabit arama]
    L <--> T[[Araçlar]]
    R --> T
    T --> G[(git CLI)]
    T --> I[(SQLite + FTS5<br/>.gitex/index.db)]
    T --> X[maskeleme]
    X --> L
    R --> A[Tek LLM çağrısı]
    L --> V{Kaynak kontrolü}
    A --> V
    V -- hepsi doğrulandı --> O([Cevap + kaynaklar])
    V -- bilinmeyen SHA / MR --> F[Düzeltme turu] --> V2{Hâlâ yanlış mı?}
    V2 -- evet --> W([⚠ işaretli cevap])
    V2 -- hayır --> O
    S[gitex sync] --> GL[(GitLab API)] --> I
```

| Modele sunulan araç | Amacı |
|---|---|
| `search_commits` | Commit mesajlarında tam metin arama; yol, yazar ve tarih filtreleri |
| `pickaxe` | Bir metnin ya da regex'in eklendiği/kaldırıldığı commit'ler (`git log -S` / `-G`) |
| `file_history` | Yeniden adlandırmaları izleyen dosya geçmişi |
| `line_history` | Bir satır aralığının evrimi (`git log -L`) |
| `blame` | Her satıra en son hangi commit'in dokunduğu |
| `get_commit` | Metadata, değişen dosyalar, tag ve branch'ler, bağlı MR ve kırpılmış diff |
| `list_paths` | Glob ya da alt dize ile doğru yolu bulur |
| `search_mrs` · `get_mr` | Merge request, review yorumu ve issue'lar — yalnızca GitLab ayarlıysa sunulur |

Araç çıktıları karakter bütçesine göre boyutlanmış sade metindir; kırpma her zaman belirtilir, böylece
model sorgusunu daraltması gerektiğini bilir.

<a id="yapilandirma"></a>

## ⚙️ Yapılandırma

gitex şunları okur (sonraki öncekini ezer):

1. `~/.config/gitex/config.toml` (ya da `GITEX_CONFIG` ile verilen yol)
2. `<repo>/.gitex/config.toml`
3. Ortam değişkenleri: `GITEX_LLM_PROVIDER`, `GITEX_LLM_MODEL`, `GITEX_LLM_BASE_URL`,
   `GITEX_LLM_MODE`, `GITEX_GITLAB_URL`, `GITEX_GITLAB_PROJECT`

> [!IMPORTANT]
> Sırlar config dosyalarına yazılmaz. LLM anahtarı `llm.api_key_env` ile adı verilen değişkenden
> (varsayılan `GITEX_LLM_API_KEY`), GitLab token'ı `GITEX_GITLAB_TOKEN`'dan okunur.

```toml
[llm]
provider = "openai_compat"        # veya "anthropic"
model = "qwen2.5-7b-instruct"
base_url = "http://localhost:8000/v1"
api_key_env = "GITEX_LLM_API_KEY"
mode = "agent"                    # "agent" (tool-use) veya "simple"
max_tool_calls = 12
temperature = 0.1                 # yalnızca openai_compat'a gönderilir

[privacy]
send_diffs = true                 # false: LLM'e yalnızca metadata ve mesajlar gider
max_diff_chars = 12000
exclude_paths = ["*.env", "*.pem", "*.key", "secrets/**", "*.lock"]

[gitlab]
url = "https://gitlab.com"
project = "grup/proje"
```

<details>
<summary><b>Tüm <code>[llm]</code> seçenekleri</b></summary>

| Anahtar | Varsayılan | Açıklama |
|---|---|---|
| `provider` | `openai_compat` | `openai_compat` (vLLM, Ollama, OpenAI) ya da `anthropic` |
| `model` | `qwen2.5-7b-instruct` | Uç noktanın beklediği model adı |
| `base_url` | — | `openai_compat` için zorunlu |
| `api_key_env` | `GITEX_LLM_API_KEY` | Anahtarı tutan ortam değişkeninin adı |
| `mode` | `agent` | `agent` ya da `simple` |
| `max_tool_calls` | `12` | Agent modunda soru başına araç çağrısı bütçesi |
| `temperature` | `0.1` | Yalnızca `openai_compat`'a gönderilir |
| `max_tokens` | sağlayıcı varsayılanı | `openai_compat` için 2048, `anthropic` için 16000 |
| `timeout` | `120` | İstek zaman aşımı (saniye) |
| `tool_output_chars` | `8000` | Tek bir araç çıktısının karakter bütçesi |
| `context_chars` | `40000` | Simple modda toplam bağlam bütçesi |
| `simple_top_n` | `6` | Simple modda detayı bağlama konan commit sayısı |
| `anthropic_fallbacks` | `true` | Claude API'nin reddedilen isteği yedek modelde yeniden denemesi |

</details>

<a id="model-saglayicilari"></a>

### Model sağlayıcıları

<details open>
<summary><b>vLLM</b></summary>

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

Tool calling için `--enable-auto-tool-choice` ve modele uygun bir parser gerekir. Bunlar yoksa
`mode = "simple"` kullanın.

</details>

<details>
<summary><b>Ollama</b></summary>

```toml
[llm]
provider = "openai_compat"
model = "qwen2.5:7b"
base_url = "http://localhost:11434/v1"
mode = "simple"                   # küçük modellerde genelde daha isabetli
```

</details>

<details>
<summary><b>Claude (Anthropic API)</b></summary>

```toml
[llm]
provider = "anthropic"
model = "claude-opus-5-5"
api_key_env = "ANTHROPIC_API_KEY"
mode = "agent"
```

Claude API bir isteği reddederse istek sunucu tarafında yedek bir modelde yeniden denenir
(`anthropic_fallbacks = true` varsayılan; kapatmak için `false`).

</details>

<details>
<summary><b>OpenAI</b></summary>

```toml
[llm]
provider = "openai_compat"
model = "<model-adı>"
base_url = "https://api.openai.com/v1"
api_key_env = "OPENAI_API_KEY"
```

</details>

### Agent mı, simple mı?

| | `agent` | `simple` |
|---|---|---|
| Nasıl arar | Model döngü içinde araç seçer | Anahtar kelime, kod terimi, yol ve tarihler kurallarla çıkarılır (kurallar bir şey bulamazsa tek küçük LLM çağrısı) |
| LLM çağrısı | Birkaç tane, `max_tool_calls` ile sınırlı | Bir (en fazla iki) |
| En uygun | Claude, tool calling'i sağlam büyük açık modeller | Küçük yerel modeller, tool calling desteklemeyen sunucular |
| `chat`'te takip | Tam konuşma geçmişi | Önceki turlar metin olarak eklenir |

## 🦊 GitLab entegrasyonu

```bash
export GITEX_GITLAB_TOKEN=...      # read_api yetkili bir token
gitex sync                          # son senkrondan artımlı; baştan için --full
```

- Merge edilmiş ve açık merge request'leri, sistem dışı review yorumlarını (diff yorumlarında dosya
  ve satırla) ve MR'ın kapattığı ya da ilişkili olduğu issue'ları senkronlar.
- `updated_after` ile artımlıdır; merge edilmeden kapatılan MR'lar indeksten silinir.
- HTTP 429'da `Retry-After`'a uyar, sayfalamayı otomatik yapar.
- Commit'leri MR'ın commit'leri, `merge_commit_sha` ve `squash_commit_sha` üzerinden MR'lara eşler.

`[gitlab]` bölümü yoksa gitex yerel git ile tam çalışır ve MR araçları modele hiç sunulmaz.

## 🔐 Gizlilik ve güvenlik

| Önlem | Ayrıntı |
|---|---|
| Diskte diff yok | İndeks metadata ve mesajları saklar; diff'ler gerektiğinde git'ten okunur |
| Sır maskeleme | Anahtar, token, parola, private key, JWT ve bağlantı dizeleri `[REDACTED]` olur |
| Hariç yollar | `exclude_paths` ile eşleşen dosyaların diff'i hiç gönderilmez |
| Yalnızca metadata | `send_diffs = false` tüm araçlardan diff ve kod satırlarını kaldırır |
| Göndermeden denetim | `--show-context` istek yapılmadan önce mesajların tamamını basar |
| Diskte sır yok | Anahtar ve token'lar yalnızca ortam değişkenlerinden okunur |

<a id="degerlendirme"></a>

## 📊 Değerlendirme

Depo, deterministik bir örnek depo ve İngilizce/Türkçe 19 soruyla gelir; cevap uyduran modelleri
yakalamak için ikisinin cevabı yoktur.

```bash
uv run python -m gitex.evals                                     # config'teki model
uv run python -m gitex.evals --provider anthropic --model claude-opus-5-5
uv run python -m gitex.evals --mode simple --model qwen2.5:7b \
    --base-url http://localhost:11434/v1 --output rapor.json
```

| Metrik | Anlamı |
|---|---|
| Kaynak isabeti | Beklenen commit'lerin doğrulanmış kaynak olarak gösterilme oranı |
| Tam isabet | Beklenen commit'lerin hepsinin gösterildiği soruların oranı |
| Uydurma referans oranı | Doğrulanamayan referanslar ÷ cevaplardaki tüm referanslar |
| "Bulamadım" doğruluğu | Cevapsız sorularda SHA vermeden "bulamadım" denme oranı |
| Metin eşleşmesi | Beklenen olguların (isim, tarih, sürüm) cevapta geçmesi |

Sorular [`evals/questions.toml`](evals/questions.toml) içinde.

## 🗂 Proje yapısı

```text
src/gitex/
├── cli.py            Typer komutları
├── config.py         TOML + ortam değişkeni yükleme, doğrulama (pydantic)
├── session.py        ask, explain ve chat'in ortak soru-cevap oturumu
├── redact.py         Sır maskeleme
├── git/              git CLI okuyucu ve veri modelleri
├── index/            SQLite şeması ve migration, artımlı indeksleyici, arama
├── gitlab/           python-gitlab sarmalayıcı, artımlı senkron
├── llm/              Sağlayıcı protokolü, OpenAI uyumlu ve Anthropic adaptörleri
├── agent/            Araçlar, tool-use döngüsü, simple mod, promptlar, kaynak kontrolü
└── evals/            Örnek depo kurucu ve değerlendirme koşucusu
```

Tasarım kararları ve her bağımlılığın gerekçesi [`docs/decisions.md`](docs/decisions.md) içinde.

## 🛠 Geliştirme

```bash
uv sync
uv run pytest                                      # hiçbir test ağa çıkmaz
uv run ruff check . && uv run ruff format --check .
uv run mypy                                        # strict
```

CI (`.gitlab-ci.yml`) her push'ta lint, tip denetimi ve testleri çalıştırır.

## 🗺 Yol haritası

- [ ] Hibrit arama: FTS5 + `sqlite-vec` ile embedding (arama arayüzü buna göre soyutlandı)
- [ ] `--json` çıktısı üzerine kurulu bir MCP sunucusu
- [ ] `ask` ve `chat`'te akışlı (streaming) cevaplar
- [ ] GitLab merge request'lerinin yanında GitHub pull request'leri

## 📄 Lisans

[MIT](LICENSE) · Değişiklikler [CHANGELOG.md](CHANGELOG.md) içinde.
