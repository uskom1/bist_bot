# 📈 BIST Quant Scanner & Telegram Bildirim Botu

Borsa İstanbul (**BIST**) hisselerinde sabah açılış kırılımlarını (**tavan adaylarını**) ve akşam kapanış sıkışmalarını (**ertesi gün hazırlık hisselerini**) `tradingview-screener` üzerinden tarayıp sonuçları sektör kümeleme analiziyle birlikte **Telegram**'a gönderen, hem **GitHub Actions** hem de lokalde **`uv` veya `pyenv` (`bist` sanal ortamı)** ile izole çalışan uçtan uca bir kantitatif tarama projesidir.

---

## 📂 Proje Dosya Yapısı

```text
.
├── .github/
│   └── workflows/
│       └── bist_scanner.yml   # İzole 'bist' (uv) önbellekli GitHub Actions otomasyonu
├── src/
│   └── scanner.py             # Sabah ve akşam BIST tarama & Telegram bildirim motoru
├── requirements.txt           # Python bağımlılıkları
├── run_local.sh               # uv / pyenv ile 'bist' sanal ortamını kurup çalıştıran betik
└── README.md                  # Kurulum ve kullanım kılavuzu
```

---

## 🧠 Tarama Stratejileri ve Modlar

### 1. Sabah Kırılım & Tavan Adayları (`morning_breakout` - 10:15 TSİ)
Sabah seans açıldıktan sonra güçlü hacim ve momentumla **Klasik Pivot R1** direncini kıran hisseleri tespit eder:
- **Günlük Değişim (`change`):** `%1.5` ile `%6.0` arasında (henüz tavana kilitlememiş ama güçlü alım gelmiş).
- **Göreceli Hacim (`relative_volume_10d_calc`):** `> 1.8` (10 günlük ortalama hacmin en az 1.8 katı).
- **RSI (14):** `55` ile `72` arasında (momentumun "Sweet Spot" bölgesi).
- **Trend Filtresi:** `close > EMA20` ve `close > EMA50`.
- **Direnç Kırılımı:** `close >= Pivot.M.Classic.R1`.
- **Sıralama:** Göreceli hacme göre azalan, maksimum **15 hisse**.

### 2. Akşam Kapanış Sıkışmaları (`evening_squeeze` - 18:20 TSİ)
Günü en yükseğine yakın (alıcılı Marubozu mumu ile) kapatan ve ertesi sabah kırılıma hazır hisseleri tespit eder:
- **Günlük Değişim (`change`):** `%0.5` ile `%4.5` arasında.
- **RSI (14):** `52` ile `65` arasında.
- **Trend Filtresi:** `close > EMA9` ve `close > EMA20`.
- **Teknik Derecelendirme (`Recommend.All`):** `> 0.1` (*Al* veya *Güçlü Al*).
- **Mum Gücü (Pandas Filtresi):** `(close - low) / (high - low) >= 0.75` (günün en yüksek seviyesine yakın kapanış, `high != low` korumalı).
- **Sıralama:** Göreceli hacme göre azalan, maksimum **15 hisse**.

---

## 🤖 Telegram Bot Kurulumu

1. Telegram'da [@BotFather](https://t.me/BotFather) hesabına gidin ve `/newbot` komutuyla yeni bir bot oluşturun.
2. BotFather'ın verdiği **HTTP API Token** değerini kopyalayın (`TELEGRAM_BOT_TOKEN`).
3. Botunuza Telegram üzerinden `/start` mesajı gönderin (veya botu bir gruba/kanala ekleyip yönetici yapın).
4. `TELEGRAM_CHAT_ID` değerinizi öğrenmek için tarayıcınızda şu adresi açın:
   ```text
   https://api.telegram.org/bot<TELEGRAM_BOT_TOKEN>/getUpdates
   ```
   JSON çıktısındaki `"chat":{"id": ...}` alanı sizin `TELEGRAM_CHAT_ID` değerinizdir.

---

## ☁️ GitHub Actions Kurulumu (Otomatik Çalıştırma)

Proje, hafta içi her gün Türkiye saatiyle (**TSİ / UTC+3**) **10:15** ve **18:20**'de GitHub Actions üzerinde **`uv`** ile oluşturulan **`bist`** sanal ortamında otomatik çalışır.

### 1. GitHub Secrets Tanımlama
GitHub deponuzda sırasıyla **Settings** -> **Secrets and variables** -> **Actions** menüsüne gidin ve **New repository secret** butonuna tıklayarak aşağıdaki iki gizli değişkeni ekleyin:

| Secret Adı | Açıklama | Örnek Değer |
| :--- | :--- | :--- |
| `TELEGRAM_BOT_TOKEN` | BotFather'dan alınan Telegram Bot API anahtarı | `1234567890:AAHxyz...` |
| `TELEGRAM_CHAT_ID` | Bildirimlerin gönderileceği kullanıcı, grup veya kanal ID'si | `987654321` veya `-100123456789` |

### 2. Manuel Tetikleme (`workflow_dispatch`)
- GitHub deponuzda **Actions** sekmesine tıklayın.
- Sol menüden **BIST Quant Scanner** iş akışını seçin.
- Sağ taraftaki **Run workflow** açılır menüsünden `morning_breakout` veya `evening_squeeze` modunu seçip **Run workflow** butonuna basın.

---

## 💻 Lokal Ortamda Kurulum ve Çalıştırma (`bist` Sanal Ortamı)

### 1. `.env` Dosyasını Oluşturun
Proje kök dizininde `.env` adında bir dosya oluşturun ve bilgilerinizi girin:

```env
TELEGRAM_BOT_TOKEN=1234567890:AAHxyz_sizin_bot_tokeniniz
TELEGRAM_CHAT_ID=987654321
SCAN_MODE=morning_breakout
```

### 2. Otomatik Betik ile Çalıştırma (`run_local.sh`)
`run_local.sh` betiği sisteminizde `uv` veya `pyenv` olup olmadığını kontrol eder, **`bist`** adında sanal ortamı oluşturur, bağımlılıkları kurar ve taramayı başlatır:

```bash
chmod +x run_local.sh

# Sabah kırılım modunda çalıştır:
./run_local.sh morning_breakout

# Akşam kapanış sıkışması modunda çalıştır:
./run_local.sh evening_squeeze

# Telegram'a mesaj atmadan sadece terminalde test et (--dry-run):
./run_local.sh morning_breakout --dry-run
```

---

### 3. Manuel Kurulum Seçenekleri (`uv` veya `pyenv`)

#### Seçenek A: `uv` ile `bist` Sanal Ortamı (Önerilen - Çok Hızlı)
```bash
# 1. 'bist' adında sanal ortam oluştur
uv venv bist --python 3.11

# 2. Sanal ortamı aktif et
# Linux / macOS / WSL2:
source bist/bin/activate
# Windows (PowerShell):
.\bist\Scripts\Activate.ps1

# 3. Paketleri 'bist' ortamına yükle
uv pip install -r requirements.txt

# 4. Tarayıcıyı çalıştır
python src/scanner.py morning_breakout
python src/scanner.py evening_squeeze --dry-run
```

#### Seçenek B: `pyenv` (`pyenv-virtualenv`) ile `bist` Sanal Ortamı
```bash
# 1. Python 3.11 kur (eğer kurulu değilse) ve 'bist' ortamını oluştur
pyenv install -s 3.11.9
pyenv virtualenv 3.11.9 bist

# 2. Proje dizininde 'bist' ortamını aktif et (.python-version oluşturur)
pyenv local bist

# 3. Paketleri yükle
pip install --upgrade pip
pip install -r requirements.txt

# 4. Tarayıcıyı çalıştır
python src/scanner.py morning_breakout
python src/scanner.py evening_squeeze --dry-run
```
