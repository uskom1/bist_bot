#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Borsa İstanbul (BIST) Quantitative Hisse Tarayıcı ve Telegram Bildirim Sistemi.

Modlar:
1. morning_breakout : Sabah açılış kırılımları ve tavan adayları (Saat 10:15 TSİ)
2. evening_squeeze  : Akşam kapanış sıkışmaları ve ertesi gün hazırlık (Saat 18:20 TSİ)
"""

import argparse
import logging
import math
import os
import sys
from datetime import datetime, timezone, timedelta
from typing import List, Optional, Tuple

import pandas as pd
import requests
from dotenv import load_dotenv
from tradingview_screener import Column, Query

# Log yapılandırması
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger("BISTScanner")

# Türkiye Saat Dilimi (UTC+3)
TZ_TR = timezone(timedelta(hours=3))

# Telegram maksimum mesaj uzunluğu (güvenlik payı ile)
TELEGRAM_MAX_LEN = 4096
SAFE_CHUNK_LEN = 3900

# TradingView üzerinden çekilecek ortak sütunlar
SELECT_COLUMNS = [
    "name",
    "close",
    "open",
    "high",
    "low",
    "change",
    "relative_volume_10d_calc",
    "RSI",
    "EMA9",
    "EMA20",
    "EMA50",
    "Pivot.M.Classic.R1",
    "Recommend.All",
    "sector",
    "volume",
    "Value.Traded",
]


def safe_float(val: object, default: float = 0.0) -> float:
    """NaN veya None değerleri güvenli şekilde float tipine çevirir."""
    if val is None or pd.isna(val):
        return default
    try:
        f_val = float(val)
        return default if math.isnan(f_val) or math.isinf(f_val) else f_val
    except (ValueError, TypeError):
        return default


def safe_str(val: object, default: str = "Belirtilmemiş") -> str:
    """NaN veya None metin değerlerini güvenli şekilde string tipine çevirir."""
    if val is None or pd.isna(val):
        return default
    text = str(val).strip()
    return text if text and text.lower() != "nan" else default


def classify_risk_group(value_traded: object) -> str:
    """
    Günlük işlem cirosuna (Value.Traded / TL) göre otomatik risk grubu sınıflandırması yapar:
    - Günlük Ciro > 500M TL         -> 🛡️ Düşük Risk (Blue-Chip)
    - Günlük Ciro 100M - 500M TL    -> ⚖️ Orta Risk (Mid-Cap)
    - Günlük Ciro < 100M TL         -> ⚡ Yüksek Risk (Sığ/Tavan Adayı)
    """
    turnover = safe_float(value_traded, default=0.0)
    if turnover > 500_000_000:
        return "🛡️ Düşük Risk (Blue-Chip)"
    if turnover >= 100_000_000:
        return "⚖️ Orta Risk (Mid-Cap)"
    return "⚡ Yüksek Risk (Sığ/Tavan Adayı)"


def format_turnover_tl(value_traded: object) -> str:
    """Günlük işlem cirosunu okunaklı TL formatına (Milyar / Milyon TL) çevirir."""
    turnover = safe_float(value_traded, default=0.0)
    if turnover >= 1_000_000_000:
        return f"{turnover / 1_000_000_000:.2f} Milyar ₺"
    if turnover >= 1_000_000:
        return f"{turnover / 1_000_000:.1f}M ₺"
    if turnover > 0:
        return f"{turnover:,.0f} ₺"
    return "N/A"


def fetch_morning_breakout() -> pd.DataFrame:
    """
    Mod A: morning_breakout (Sabah Kırılım & Tavan Adayları - Saat 10:15 TSİ)
    Filtreler:
    - change: %1.5 ile %6.0 arasında
    - relative_volume_10d_calc > 1.8
    - RSI: 55 ile 72 arasında
    - close > EMA20 ve close > EMA50
    - close >= Pivot.M.Classic.R1
    - Sıralama: relative_volume_10d_calc azalan, maksimum 15 hisse
    """
    logger.info("Mod A (morning_breakout) sorgusu TradingView üzerinde çalıştırılıyor...")

    q = (
        Query()
        .set_markets("turkey")
        .select(*SELECT_COLUMNS)
        .where(
            Column("change").between(1.5, 6.0),
            Column("relative_volume_10d_calc") > 1.8,
            Column("RSI").between(55, 72),
            Column("close") > Column("EMA20"),
            Column("close") > Column("EMA50"),
            Column("close") >= Column("Pivot.M.Classic.R1"),
        )
        .order_by("relative_volume_10d_calc", ascending=False)
        .limit(15)
    )

    total_count, df = q.get_scanner_data()
    logger.info(f"TradingView sorgusu tamamlandı. Eşleşen toplam: {total_count}, Çekilen: {len(df)}")
    return df


def fetch_evening_squeeze() -> pd.DataFrame:
    """
    Mod B: evening_squeeze (Akşam Kapanış & Ertesi Gün Hazırlık - Saat 18:20 TSİ)
    Filtreler:
    - change: %0.5 ile %4.5 arasında
    - RSI: 52 ile 65 arasında
    - close > EMA9 ve close > EMA20
    - Recommend.All > 0.1
    - Pandas ek filtre: (close - low) / (high - low) >= 0.75 (high != low kontrolü ile)
    - Sıralama: relative_volume_10d_calc azalan, maksimum 15 hisse
    """
    logger.info("Mod B (evening_squeeze) sorgusu TradingView üzerinde çalıştırılıyor...")

    # Pandas tarafında mum kapanış filtresi uygulanacağı için ilk aşamada daha geniş limit çekilir
    q = (
        Query()
        .set_markets("turkey")
        .select(*SELECT_COLUMNS)
        .where(
            Column("change").between(0.5, 4.5),
            Column("RSI").between(52, 65),
            Column("close") > Column("EMA9"),
            Column("close") > Column("EMA20"),
            Column("Recommend.All") > 0.1,
        )
        .order_by("relative_volume_10d_calc", ascending=False)
        .limit(150)
    )

    total_count, df = q.get_scanner_data()
    logger.info(f"TradingView ön sorgusu tamamlandı. Aday sayısı: {len(df)} (Toplam: {total_count})")

    if df.empty:
        return df

    # Sıfıra bölünme hatasına karşı (high != low ve high > low) kontrolü
    df = df.copy()
    df["high"] = pd.to_numeric(df["high"], errors="coerce")
    df["low"] = pd.to_numeric(df["low"], errors="coerce")
    df["close"] = pd.to_numeric(df["close"], errors="coerce")
    df["relative_volume_10d_calc"] = pd.to_numeric(df["relative_volume_10d_calc"], errors="coerce").fillna(0.0)

    valid_range_mask = (df["high"].notna()) & (df["low"].notna()) & (df["close"].notna()) & (df["high"] > df["low"])
    df = df[valid_range_mask].copy()

    if df.empty:
        return df

    # Günün en yükseğine yakın kapanış oranı: (close - low) / (high - low) >= 0.75
    df["close_position_ratio"] = (df["close"] - df["low"]) / (df["high"] - df["low"])
    df = df[df["close_position_ratio"] >= 0.75].copy()

    # Göreceli hacme göre azalan sırala ve maksimum 15 hisse al
    df = df.sort_values(by="relative_volume_10d_calc", ascending=False).head(15).reset_index(drop=True)
    logger.info(f"Marubozu / alıcılı kapanış filtresi sonrası kalan hisse sayısı: {len(df)}")
    return df


def extract_top_sectors(df: pd.DataFrame, top_n: int = 2) -> List[Tuple[str, int]]:
    """Çıkan hisselerin sector sütununa bakarak en çok kümelendiği ilk N sektörü döndürür."""
    if df.empty or "sector" not in df.columns:
        return []

    sectors = (
        df["sector"]
        .dropna()
        .astype(str)
        .str.strip()
        .replace({"": "Diğer", "nan": "Diğer", "None": "Diğer"})
    )
    if sectors.empty:
        return []

    counts = sectors.value_counts().head(top_n)
    return [( str(sector), int(count) ) for sector, count in counts.items()]


def build_telegram_message(df: pd.DataFrame, scan_mode: str) -> str:
    """Tarama sonuçlarını şık ve okunaklı bir Telegram Markdown mesajına dönüştürür."""
    now_tr = datetime.now(TZ_TR).strftime("%d.%m.%Y %H:%M")

    if scan_mode == "morning_breakout":
        header_title = "🚀 *BIST SABAH KIRILIM & TAVAN ADAYLARI*"
        mode_desc = "Sabah Açılış Momentum & Pivot R1 Kırılım Taraması (10:15 TSİ)"
        criteria_note = (
            "📌 _Filtreler: Değişim %1.5-%6.0 | Rel.Hacim > 1.8x | RSI 55-72 | "
            "Fiyat > EMA20 & EMA50 | Fiyat >= Pivot R1_"
        )
    else:
        header_title = "🌙 *BIST AKŞAM KAPANIŞ SIKIŞMALARI*"
        mode_desc = "Günü Zirvede Kapatan & Yarına Hazır Hisseler (18:20 TSİ)"
        criteria_note = (
            "📌 _Filtreler: Değişim %0.5-%4.5 | RSI 52-65 | Fiyat > EMA9 & EMA20 | "
            "Teknik: AL | Mum Kapanışı >= %75_"
        )

    lines = [
        header_title,
        f"🕒 _Tarih/Saat:_ `{now_tr} TSİ`",
        f"🧭 _Strateji:_ {mode_desc}",
        criteria_note,
        "━━━━━━━━━━━━━━━━━━━━━━",
    ]

    if df.empty:
        lines.append("\nℹ️ *Bilgi:* Mevcut piyasa koşullarında kriterlere uyan hisse bulunamadı.")
        lines.append("\n_Not: Piyasa hacimsiz veya filtre aralıkları dışında seyrediyor olabilir._")
        return "\n".join(lines)

    # Sektör Kümeleme Analizi
    top_sectors = extract_top_sectors(df, top_n=2)
    if top_sectors:
        lines.append("🔥 *Öne Çıkan Sektörler:*")
        for idx, (sec_name, sec_count) in enumerate(top_sectors, start=1):
            lines.append(f"  {idx}. `{sec_name}` ({sec_count} Hisse)")
        lines.append("━━━━━━━━━━━━━━━━━━━━━━")

    lines.append(f"📊 *Taranan Sonuçlar ({len(df)} Hisse):*\n")

    for rank, (_, row) in enumerate(df.iterrows(), start=1):
        symbol = safe_str(row.get("name"), default="BIST")
        close_price = safe_float(row.get("close"))
        change_pct = safe_float(row.get("change"))
        rel_vol = safe_float(row.get("relative_volume_10d_calc"))
        rsi_val = safe_float(row.get("RSI"))
        pivot_r1 = safe_float(row.get("Pivot.M.Classic.R1"))
        sector_name = safe_str(row.get("sector"), default="Belirtilmemiş")

        # Günlük işlem cirosu (Value.Traded yoksa close * volume fallback)
        raw_value = row.get("Value.Traded")
        if raw_value is None or pd.isna(raw_value):
            raw_value = close_price * safe_float(row.get("volume"))
        risk_label = classify_risk_group(raw_value)
        turnover_str = format_turnover_tl(raw_value)

        tv_url = f"https://tr.tradingview.com/chart/?symbol=BIST:{symbol}"
        pivot_str = f"{pivot_r1:.2f} ₺" if pivot_r1 > 0 else "N/A"

        stock_block = [
            f"*{rank}.* [{symbol}]({tv_url})  —  `{close_price:.2f} ₺` (*{change_pct:+.2f}%*)",
            f"   ├ 📈 *Rel. Hacim:* `{rel_vol:.2f}x` | *RSI:* `{rsi_val:.1f}`",
            f"   ├ 💰 *Günlük Ciro:* `{turnover_str}`",
            f"   ├ 🏷 *Sınıf:* {risk_label}",
            f"   ├ 🎯 *Pivot R1:* `{pivot_str}`",
            f"   └ 🏭 *Sektör:* _{sector_name}_",
        ]

        if "close_position_ratio" in row and pd.notna(row.get("close_position_ratio")):
            close_pos = safe_float(row.get("close_position_ratio")) * 100
            stock_block.insert(2, f"   ├ 🕯 *Mum Gücü (Kapanış/Zirve):* `%{close_pos:.0f}`")

        lines.append("\n".join(stock_block))
        lines.append("")

    lines.append("⚠️ _Bu bildirim algoritmik veri taramasıdır, yatırım tavsiyesi değildir._")
    return "\n".join(lines)


def split_message(text: str, max_len: int = SAFE_CHUNK_LEN) -> List[str]:
    """Telegram 4096 karakter sınırını aşan mesajları satır bütünlüğünü bozmadan böler."""
    if len(text) <= TELEGRAM_MAX_LEN:
        return [text]

    chunks: List[str] = []
    current_lines: List[str] = []
    current_length = 0

    for line in text.split("\n"):
        line_len = len(line) + 1  # +1 newline karakteri
        if current_length + line_len > max_len and current_lines:
            chunks.append("\n".join(current_lines))
            current_lines = [line]
            current_length = line_len
        else:
            current_lines.append(line)
            current_length += line_len

    if current_lines:
        chunks.append("\n".join(current_lines))

    return chunks


def send_telegram_notification(message: str, bot_token: str, chat_id: str) -> bool:
    """Mesajı Telegram Bot API üzerinden gönderir. 4096 karakteri aşarsa parçalara böler."""
    url = f"https://api.telegram.org/bot{bot_token}/sendMessage"
    chunks = split_message(message)

    all_success = True
    for idx, chunk in enumerate(chunks, start=1):
        payload = {
            "chat_id": chat_id,
            "text": chunk,
            "parse_mode": "Markdown",
            "disable_web_page_preview": True,
        }
        try:
            response = requests.post(url, json=payload, timeout=15)
            response.raise_for_status()
            logger.info(f"Telegram mesaj parçası ({idx}/{len(chunks)}) başarıyla gönderildi.")
        except requests.exceptions.RequestException as exc:
            logger.error(f"Telegram gönderim hatası (Parça {idx}/{len(chunks)}): {exc}")
            # Markdown parse hatası ihtimaline karşı düz metin fallback denemesi
            try:
                payload.pop("parse_mode", None)
                fallback_resp = requests.post(url, json=payload, timeout=15)
                fallback_resp.raise_for_status()
                logger.info(f"Telegram mesaj parçası ({idx}/{len(chunks)}) düz metin olarak gönderildi.")
            except requests.exceptions.RequestException as fallback_exc:
                logger.error(f"Telegram fallback gönderimi de başarısız oldu: {fallback_exc}")
                all_success = False

    return all_success


def resolve_scan_mode(cli_mode: Optional[str]) -> str:
    """Komut satırı argümanı veya SCAN_MODE ortam değişkeninden çalışma modunu belirler."""
    valid_modes = {"morning_breakout", "evening_squeeze"}

    mode = (cli_mode or os.environ.get("SCAN_MODE") or "").strip().lower()
    if mode in valid_modes:
        return mode

    # Belirtilmemişse Türkiye saatine göre otomatik seç
    now_tr = datetime.now(TZ_TR)
    auto_mode = "morning_breakout" if now_tr.hour < 14 else "evening_squeeze"
    logger.warning(
        f"Geçerli bir SCAN_MODE belirtilmedi ('{mode}'). "
        f"Türkiye saatine ({now_tr.strftime('%H:%M')}) göre otomatik seçilen mod: '{auto_mode}'"
    )
    return auto_mode


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="BIST Sabah Kırılım & Akşam Sıkışma Tarayıcısı"
    )
    parser.add_argument(
        "mode",
        nargs="?",
        choices=["morning_breakout", "evening_squeeze"],
        help="Çalıştırılacak tarama modu (morning_breakout veya evening_squeeze)",
    )
    parser.add_argument(
        "--mode",
        dest="flag_mode",
        choices=["morning_breakout", "evening_squeeze"],
        help="Çalıştırılacak tarama modu (alternatif parametre)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Telegram'a göndermeden sadece konsola yazdırır.",
    )
    return parser.parse_args()


def main() -> int:
    # Lokal çalışma için .env dosyasını yükle
    load_dotenv()

    args = parse_args()
    selected_cli_mode = args.mode or args.flag_mode
    scan_mode = resolve_scan_mode(selected_cli_mode)

    logger.info(f"BIST Tarayıcı başlatıldı. Aktif Mod: {scan_mode}")

    try:
        if scan_mode == "morning_breakout":
            df_results = fetch_morning_breakout()
        else:
            df_results = fetch_evening_squeeze()
    except Exception as exc:
        logger.exception(f"TradingView veri çekme aşamasında kritik hata oluştu: {exc}")
        return 1

    message = build_telegram_message(df_results, scan_mode)

    # Konsola her durumda çıktıyı bas
    print("\n" + "=" * 60)
    print(message)
    print("=" * 60 + "\n")

    if args.dry_run:
        logger.info("--dry-run aktif olduğu için Telegram gönderimi atlandı.")
        return 0

    bot_token = os.environ.get("TELEGRAM_BOT_TOKEN", "").strip()
    chat_id = os.environ.get("TELEGRAM_CHAT_ID", "").strip()

    if not bot_token or not chat_id:
        logger.error(
            "TELEGRAM_BOT_TOKEN veya TELEGRAM_CHAT_ID ortam değişkeni tanımlanmamış! "
            "Lütfen .env dosyanızı veya GitHub Secrets ayarlarınızı kontrol edin."
        )
        return 1

    success = send_telegram_notification(message, bot_token, chat_id)
    return 0 if success else 1


if __name__ == "__main__":
    sys.exit(main())

