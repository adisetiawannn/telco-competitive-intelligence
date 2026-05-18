# Model Development Notes

## v1.0 — Baseline (Phase 2)
- Model: w11wo/indonesian-roberta-base-sentiment-classifier
- Data: 55 artikel, zero-shot (tidak ada fine-tuning)
- Hasil: positive=13, negative=0, neutral=42
- Limitasi: model tidak bisa detect negative sama sekali
- Root cause: domain mismatch — model dilatih untuk general sentiment

## v2.0 — Fine-tuned (Phase 3)
- Model: models/sentiment_v2/final
- Data: SmSA 10.859 rows (Stage 1) + 23 artikel telco (Stage 2)
- Stage 1 F1: 0.9134 (neg=0.926, neu=0.857, pos=0.957)
- Hasil: positive=18, negative=1, neutral=36
- Limitasi: masih gagal detect negative di berita telco formal
- Root cause: model masih andalkan emotional cues dari SmSA,
  bukan domain knowledge telco

## v2.1 — Fine-tuned + Rule-based (Phase 3, current)
- Model: models/sentiment_v2/final + post_process_sentiment()
- Hasil: positive=26, negative=7, neutral=22
- Improvement: negative naik dari 1 ke 7
- Limitasi rule-based:
  * Confidence di-set 0.75 (bukan 1.0) karena rules tidak sempurna
  * False positive mungkin terjadi jika signal word muncul
    dalam konteks yang berbeda
    contoh: "gangguan" bisa muncul di artikel yang sebenarnya
    positif ("Telkomsel atasi gangguan dengan sukses")
  * Rules tidak bisa capture nuance — perlu lebih banyak
    labeled telco data

## TODO untuk v3.0
- [ ] Kumpulkan minimal 300 artikel telco berlabel
- [ ] Distribusi balanced: 100 pos / 100 neg / 100 neu
- [ ] Fine-tune dengan domain-specific negative examples:
      "gangguan jaringan", "rugi", "complaint pelanggan"
- [ ] Hapus rule-based layer — replace dengan pure model
- [ ] Target F1 per class >= 0.85 untuk semua class
- [ ] Evaluate dengan held-out telco test set
      (bukan SmSA validation set)

## Catatan Engineering
- Setiap rule override di-log di level DEBUG
- Query untuk audit: grep "RULE_OVERRIDE" di logs
- Model checkpoint ada di: models/sentiment_v2/
  - stage1_best/ → best SmSA checkpoint
  - final/       → after telco domain adaptation
- Confidence 0.75 untuk rule overrides — BUKAN 1.0
  Alasan: rules kita tidak sempurna, confidence tinggi
  akan menyesatkan downstream analysis

## Kenapa confidence rule-based = 0.75, bukan 1.0
Rules adalah heuristik, bukan ground truth. 0.75 berarti:
- "sangat mungkin benar" tapi masih bisa dikoreksi
- Mempertahankan uncertainty — sistem downstream bisa re-weight
- Memungkinkan A/B test antara rule vs model
- Rules bisa di-deprecate tanpa merusak historical data
- Kalau confidence = 1.0: rule jadi otoritas absolut,
  error kecil jadi kebenaran permanen, tidak bisa evolve

## Security Notes — Phase 4

### Data yang dikirim ke Gemini API:
- Hanya artikel dari portal berita publik
- Tidak ada data internal atau data pelanggan

### Untuk production deployment di Telkom:
- Ganti Gemini API dengan Ollama (zero data egress)
  ATAU Google Cloud Vertex AI dengan DPA yang sudah disetujui
- Review dengan tim Information Security Telkom
- Pastikan ada Data Processing Agreement dengan vendor LLM
- Pertimbangkan on-premise LLM deployment untuk data sensitif

## Known Limitations — Content Fetcher
- Artikel dengan full_content < 200 chars di-skip
- Kemungkinan penyebab: JS-rendered, paywall, image-only
- Impact: ~5-10% artikel tidak masuk NLP pipeline
- Mitigasi future: implement summary fallback untuk artikel penting