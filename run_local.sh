#!/usr/bin/env bash
# ==============================================================================
# BIST Quant Scanner - Lokal 'bist' Sanal Ortam (uv / pyenv) Çalıştırma Betiği
# ==============================================================================

set -euo pipefail

# Betiğin bulunduğu proje kök dizinine geç
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

ENV_NAME="bist"

echo "============================================================"
echo "🚀 BIST Quant Scanner - Lokal Çalıştırıcı Başlatılıyor..."
echo "============================================================"

# 1. 'uv' veya 'pyenv' ile 'bist' sanal ortamını hazırla ve aktif et
if command -v uv >/dev/null 2>&1; then
    echo "⚡ 'uv' tespit edildi."
    if [ ! -d "$ENV_NAME" ]; then
        echo "📦 '$ENV_NAME' sanal ortamı uv ile oluşturuluyor..."
        uv venv "$ENV_NAME" --python 3.11 || uv venv "$ENV_NAME"
    else
        echo "✅ Mevcut '$ENV_NAME' sanal ortamı bulundu."
    fi

    # Windows (Git Bash) veya Linux/macOS/WSL2 uyumlu aktivasyon
    if [ -f "$ENV_NAME/bin/activate" ]; then
        # shellcheck disable=SC1091
        source "$ENV_NAME/bin/activate"
    elif [ -f "$ENV_NAME/Scripts/activate" ]; then
        # shellcheck disable=SC1091
        source "$ENV_NAME/Scripts/activate"
    fi

    echo "📥 Paketler 'uv pip' ile '$ENV_NAME' ortamına yükleniyor..."
    uv pip install -r requirements.txt

elif command -v pyenv >/dev/null 2>&1; then
    echo "🐍 'pyenv' tespit edildi."
    eval "$(pyenv init -)"
    if command -v pyenv-virtualenv-init >/dev/null 2>&1; then
        eval "$(pyenv virtualenv-init -)"
    fi

    if ! pyenv versions --bare | grep -qx "$ENV_NAME"; then
        echo "📦 '$ENV_NAME' pyenv sanal ortamı oluşturuluyor..."
        pyenv virtualenv "$ENV_NAME"
    else
        echo "✅ Mevcut '$ENV_NAME' pyenv sanal ortamı bulundu."
    fi

    pyenv activate "$ENV_NAME" || pyenv local "$ENV_NAME"
    echo "📥 Paketler '$ENV_NAME' ortamına yükleniyor..."
    python -m pip install --upgrade pip --quiet
    python -m pip install -r requirements.txt --quiet

else
    echo "⚠️  Sistemde 'uv' veya 'pyenv' bulunamadı. 'uv' otomatik kuruluyor..."
    curl -LsSf https://astral.sh/uv/install.sh | sh
    export PATH="$HOME/.local/bin:$HOME/.cargo/bin:$PATH"

    uv venv "$ENV_NAME"
    # shellcheck disable=SC1091
    source "$ENV_NAME/bin/activate"
    uv pip install -r requirements.txt
fi

echo "🐍 Aktif Python yorumlayıcısı: $(which python)"

# 2. .env dosyası kontrolü ve ortam değişkenlerinin yüklenmesi
if [ -f ".env" ]; then
    echo "🔐 '.env' dosyası bulundu, ortam değişkenleri yükleniyor..."
    set -a
    # Windows CRLF satır sonlarını temizleyerek güvenli şekilde oku
    # shellcheck disable=SC1090
    source <(sed 's/\r$//' .env)
    set +a
else
    echo "⚠️  UYARI: Proje dizininde '.env' dosyası bulunamadı!"
    echo "   Telegram bildirimi için TELEGRAM_BOT_TOKEN ve TELEGRAM_CHAT_ID gereklidir."
fi

# 3. Çalışma modunu belirle (1. argüman -> SCAN_MODE -> varsayılan: morning_breakout)
MODE="${1:-${SCAN_MODE:-morning_breakout}}"
export SCAN_MODE="$MODE"

echo "🔍 Tarama Modu: $SCAN_MODE"
echo "============================================================"

# Ek argümanlar varsa (örn. --dry-run) koruyarak çalıştır
if [ $# -gt 0 ]; then
    shift
fi

python src/scanner.py "$SCAN_MODE" "$@"
