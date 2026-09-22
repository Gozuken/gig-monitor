# Reddit İş Takip

r/forhire, r/slavelabour ve r/jobbit'teki **iş veren (Hiring)** ilanlarını otomatik toplayıp filtreleyen ve web panelinden takip etmeni sağlayan araç. 

Reddit API'si / OAuth / kredensiyal **gerektirmez** — resmi RSS feed'lerini kullanır.

## Özellikler

- 🔍 **RSS tabanlı** — PRAW/API anahtarı yok, `feedparser` ile resmi feed'ler
- 🧹 **Akıllı filtreleme** — `[For Hire]`/`[offer]` (rakip/self-promo) ilanları otomatik elenir; kapatılmış (`Hired`) ve 5 günden eski ilanların dışarıda bırakılır
- 🔁 **Dedup** — aynı ilan yalnızca bir kez kaydedilir, her koşuda Tazelenir
- ⚙️ **Kontrol paneli** — Flask web arayüzü: ilan listesi, anahtar kelime süzme, subreddit seçimi, otomatik çekim aralığı
- 🔔 **Otomatik çekim** — arka plan scheduler (saniye cinsinden interval, panelden açılır)
- 📦 **SQLite** — tüm geçmiş tek dosyada (`jobs.db`)

## Kurulum

```bash
cd reddit-job-tracker
python -m pip install -r requirements.txt
```

İsteğe bağlı: `cp .env.example .env` (RSS User-Agent ayarlayabilirsin).

## Kullanım

```bash
python main.py serve          # kontrol paneli → http://127.0.0.1:5000
python main.py scrape         # tek çekim + filtreleme koşusu
python main.py run --interval 600   # 10 dakikada bir otomatik çekim
```

Panelden:
- **Ayarlar** → "Şimdi çek" ile anlık çekim, anahtar kelimeler (virgülle), subreddit'ler, interval, post yaşı sınırı

## Kimin işe yarar?

Freelancer / iş arayanlar. "Uygun ilanlar" sekmesi sana uyan işleri listeler; "Elendi" sekmesi neden elendiğini gösterir (neden: `not_hiring`, `hired`, `stale`, `keyword_miss`).

## Mimari

```
scraper.py   RSS feed çekme + normalize           (feedparser)
storage.py   SQLite katmanı, upsert, ayarlar
cleaner.py   hard-rule pipeline (flair/title marker, yaş, keyword)
scheduler.py arka plan döngüsü (interval)
ui.py        Flask paneli + scheduler kontrolü
main.py      CLI (serve / scrape / run)
```

## Geliştirme yolu

- [ ] Telegram bildirimi (yeni uygun ilana anlık mesaj)
- [ ] Bütçe ayrıştırma + minimum bütçe filtresi (DB'de `budget` kolonu hazır)
- [ ] Uygunluk puanlama (scoring) — hard filtrelerden ayrı katman

## Lisans

MIT