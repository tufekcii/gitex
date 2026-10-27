# Değişiklik günlüğü

Biçim [Keep a Changelog](https://keepachangelog.com/tr/1.1.0/) esaslıdır; sürümler
[SemVer](https://semver.org/lang/tr/) izler.

## [Yayınlanmadı]

### Eklendi
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
