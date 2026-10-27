# Değişiklik günlüğü

Biçim [Keep a Changelog](https://keepachangelog.com/tr/1.1.0/) esaslıdır; sürümler
[SemVer](https://semver.org/lang/tr/) izler.

## [Yayınlanmadı]

### Eklendi
- Tek komutla kurulum: `install.cmd` / `install.ps1` (Windows) ve `install.sh` (macOS/Linux) uv'yi,
  Python 3.12'yi ve `gitex` komutunu kurar, ardından kurulum sihirbazını açar; `--uninstall` ile kaldırır.
- Dosya düzenlemeden yönetim: `gitex setup` (sihirbaz), `gitex config show/get/set/unset/list-keys/path`,
  `gitex auth login/logout/status`, `gitex doctor`.
- API anahtarları ve GitLab token'ları işletim sisteminin anahtar kasasında saklanır; ortam
  değişkeni tanımlıysa önceliklidir.

- Ücretsiz katmanı olan sağlayıcılar: Groq, Google Gemini, OpenRouter (Ollama'ya ek olarak).
- `gitex setup` modelleri sağlayıcının güncel listesinden numaralı sunar (sohbet dışı modeller
  ayıklanır, ücretsizler başta, uzun listelerde arama); listelenemezse elle yazmaya düşer.
  Evet/hayır dahil tüm seçimler numaralı; anahtar alma adresleri sihirbazda gösterilir.

### Düzeltildi
- Windows kurulumu, uv'nin stderr'e yazdığı "zaten PATH'te" bilgisinde yarıda kesiliyordu
  (PowerShell 5.1 bunu hataya çeviriyordu); sihirbaz hiç açılmıyordu.
- Kurulumu başlatan terminal yeni PATH'i göremediği için `gitex` tanınmıyordu; kurulum artık bunu
  tespit edip pencereyi yeniden açmayı ya da yapıştırılacak tek satırı gösteriyor. Kullanıcı PATH'i
  uv'ye bırakılmadan doğrulanıyor.

### Değişti
- `gitex init` artık etkin ayar yazmaz; oluşturduğu dosya yalnızca açıklama içerir ve global
  ayarları gölgelemez.

### Eklendi (dokümantasyon)
- İngilizce README (uluslararası okuyucu için) ve Türkçe `README.tr.md`; logo (açık/koyu tema),
  demo görseli, mimari diyagramı. `LICENSE` (MIT) dosyası.
- `gitex chat`: takip sorularında bağlamı koruyan etkileşimli oturum (`/yeni`, `/mod`, `/json`,
  `/çık`); büyüyen geçmiş, eski turları budamak yerine özetle yeni konuşma açılarak sıkıştırılır.
- Hata mesajları: git deposu değil, boş depo, GitLab token'ı yok / yetkisiz, proje bulunamadı,
  LLM'e ulaşılamıyor, Claude kimlik bilgisi yok — her biri çözüm ipucuyla.
- `evals/questions.toml` (19 soru) ve `python -m gitex.evals` skorlayıcısı: kaynak isabeti,
  uydurma referans oranı, metin eşleşmesi, "bulamadım" doğruluğu.

## [0.1.0] — 2026-10-27

### Eklendi
- Yerel git okuma (NUL ayraçlı `git log`, pickaxe `-S/-G`, `-L` satır geçmişi, blame, rename
  takibi, merge/boş depo desteği).
- SQLite + FTS5 indeks; Türkçe katlama (`ödeme`/`odeme`, `kullanıcı`/`kullanici`), artımlı
  indeksleme ve rebase/force-push sonrası temizlik.
- LLM katmanı: OpenAI uyumlu uç noktalar (vLLM, Ollama, OpenAI) ve Anthropic Claude API.
- Ajan (tool-use) ve simple mod; kaynak doğrulama ve uydurma referans düzeltmesi.
- Gizli bilgi maskeleme, `exclude_paths`, `send_diffs`, `--show-context`.
- GitLab senkronizasyonu: MR, review yorumları, issue'lar, SHA↔MR (merge/squash) eşlemesi.
- Komutlar: `init`, `index`, `sync`, `ask`, `explain`, `when`, `file`, `status`; `--json` çıktı.
