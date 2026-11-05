# 📈 BIST Quant Scanner & Telegram Mini App (TMA)

Borsa İstanbul (**BIST**) hisselerinde sabah açılış kırılımlarını (**tavan adaylarını**) ve akşam kapanış sıkışmalarını (**ertesi gün hazırlık hisselerini**) `tradingview-screener` üzerinden tarayıp günlük işlem cirosuna göre risk gruplarına ayıran, sonuçları **Telegram**'a gönderen ve **Telegram Mini App (WebApp)** arayüzünden tek tuşla yönetilebilen uçtan uca kantitatif tarama projesidir.

---

## 📂 Proje Dosya Yapısı

```text
.
├── .github/
│   └── workflows/
│       └── bist_scanner.yml   # İzole 'bist' (uv) önbellekli GitHub Actions otomasyonu
├── backend/
│   └── main.py                # FastAPI sunucusu (GitHub Actions tetikleyici + Canlı API)
├── frontend/
│   └── index.html             # Telegram WebApp SDK & Tailwind CSS mobil uyumlu Mini App arayüzü
├── src/
│   └── scanner.py             # Sabah ve akşam BIST tarama, ciro/risk analizi & Telegram motoru
├── .env.example               # Örnek ortam değişkenleri şablonu
├── requirements.txt           # Python bağımlılıkları (FastAPI, Uvicorn, TradingView, Pandas)
├── run_local.sh               # uv / pyenv ile 'bist' sanal ortamını kurup çalıştıran betik
└── README.md                  # Kurulum ve Telegram Mini App (BotFather) rehberi
```

---

## 🧠 Tarama Stratejileri ve Risk Sınıflandırması

### 1. Sabah Kırılım & Tavan Adayları (`morning_breakout` - 10:15 TSİ)
- **Günlük Değişim (`change`):** `%1.5` ile `%6.0` arasında.
- **Göreceli Hacim (`relative_volume_10d_calc`):** `> 1.8x`.
- **RSI (14):** `55` ile `72` arasında.
- **Trend & Direnç:** `close > EMA20`, `close > EMA50` ve `close >= Pivot.M.Classic.R1`.

### 2. Akşam Kapanış Sıkışmaları (`evening_squeeze` - 18:20 TSİ)
- **Günlük Değişim (`change`):** `%0.5` ile `%4.5` arasında.
- **RSI (14):** `52` ile `65` arasında.
- **Trend & Teknik:** `close > EMA9`, `close > EMA20` ve `Recommend.All > 0.1`.
- **Mum Gücü (Marubozu):** `(close - low) / (high - low) >= 0.75` (`high != low` korumalı).

### 3. Otomatik Ciro & Risk Grubu Sınıflandırması (`classify_risk_group`)
- **Günlük Ciro > 500M TL:** `🛡️ Düşük Risk (Blue-Chip)`
- **Günlük Ciro 100M - 500M TL:** `⚖️ Orta Risk (Mid-Cap)`
- **Günlük Ciro < 100M TL:** `⚡ Yüksek Risk (Sığ/Tavan Adayı)`

---

## 📱 Telegram Mini App (TMA) Kurulumu ve Çalıştırılması

### 1. `.env` Dosyasını Hazırlayın
`.env.example` dosyasını `.env` olarak kopyalayın ve değerlerinizi girin:

```bash
cp .env.example .env
```

```env
TELEGRAM_BOT_TOKEN=1234567890:AAHxyz_sizin_telegram_bot_tokeniniz
TELEGRAM_CHAT_ID=987654321
GITHUB_TOKEN=github_pat_11ABCDEFG_sizin_github_tokeniniz
REPO_OWNER=uskom1
REPO_NAME=bist_bot
WORKFLOW_ID=bist_scanner.yml
GITHUB_REF=main
PORT=8000
```

> **GitHub Token Nasıl Alınır?**
> GitHub'da **Settings** -> **Developer settings** -> **Personal access tokens** -> **Fine-grained tokens** -> **Generate new token** adımlarını izleyin. `bist_bot` deponuzu seçin ve **Repository permissions** altından **Actions: Read and write** yetkisi verin.

### 2. FastAPI Backend ve Mini App Sunucusunu Başlatın
`bist` sanal ortamınızı aktif edip paketleri yükledikten sonra sunucuyu başlatın:

```bash
# Windows PowerShell:
.\bist\Scripts\Activate.ps1
# Linux / macOS / WSL2:
# source bist/bin/activate

uv pip install -r requirements.txt

# Sunucuyu başlat (http://localhost:8000)
python -m uvicorn backend.main:app --host 0.0.0.0 --port 8000 --reload
```

Tarayıcınızdan `http://localhost:8000` adresine giderek Mini App arayüzünü anında test edebilirsiniz.

---

### 3. @BotFather Üzerinden Telegram Mini App Tanımlama

Telegram Mini App'lerin Telegram içinden açılabilmesi için **HTTPS** adresine ihtiyacı vardır.
- **Lokal Test İçin:** `ngrok http 8000` veya `cloudflared tunnel --url http://localhost:8000` komutuyla geçici bir `https://....ngrok-free.app` veya `https://....trycloudflare.com` adresi alın.
- **Kalıcı Dağıtım (Production) İçin:** Projeyi Render, Railway, Fly.io veya kendi VPS sunucunuza deploy edip HTTPS adresinizi alın.

Ardından Telegram'da [@BotFather](https://t.me/BotFather) ile şu adımları uygulayın:

1. **Menu Button (Sohbet Altındaki Mini App Butonu) Ekleme:**
   - `@BotFather`'a `/mybots` yazın ve botunuzu seçin.
   - **Bot Settings** -> **Menu Button** -> **Configure menu button** seçeneğine tıklayın.
   - BotFather sizden URL isteyecektir: HTTPS adresinizi (örn. `https://bist-app.onrender.com`) gönderin.
   - Buton başlığı olarak `📈 BIST Radar` yazın. Artık bot sohbet ekranının sol altında doğrudan Mini App açma butonu belirecektir!

2. **Doğrudan Mini App Linki (`/newapp`) Oluşturma (Opsiyonel):**
   - `@BotFather`'a `/newapp` komutunu gönderin ve botunuzu seçin.
   - Uygulama başlığı, açıklaması ve bir görsel yükledikten sonra **Web App URL** kısmına HTTPS adresinizi girin.
   - Kısa ad (short name) olarak `bist_scanner` belirleyin. Böylece `https://t.me/BotAdiniz/bist_scanner` linkiyle her yerden tek tıkla açılabilir.

---

## ☁️ GitHub Actions Kurulumu

GitHub deponuzda **Settings** -> **Secrets and variables** -> **Actions** menüsünden şu iki Secret'ı tanımlayın:
- `TELEGRAM_BOT_TOKEN`
- `TELEGRAM_CHAT_ID`

İş akışı hafta içi her gün otomatik çalışır veya **Telegram Mini App** içindeki **"🚀 Taramayı Şimdi Başlat"** butonuyla istediğiniz an tetiklenebilir.
