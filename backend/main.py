#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
BIST Quant Scanner - Telegram Mini App (TMA) FastAPI Backend Sunucusu.

Özellikler:
1. Mini App arayüzünü (frontend/index.html) sunar.
2. GitHub Actions workflow_dispatch API'sini güvenli şekilde Bearer Token ile tetikler.
3. Son çalışan GitHub Actions iş akışı durumunu (status/conclusion) sorgular.
4. Canlı/Özet BIST tarama sonuçlarını JSON formatında Mini App kartlarına sunar
   ve isteğe bağlı olarak Telegram'a da anlık bildirim gönderir.
"""

import hashlib
import hmac
import logging
import os
import sys
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional
from urllib.parse import parse_qsl

import pandas as pd
import requests
from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException, Header
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

# Proje kök dizinini sys.path'e ekle (src.scanner modülünü doğrudan kullanabilmek için)
BASE_DIR = Path(__file__).resolve().parent.parent
if str(BASE_DIR) not in sys.path:
    sys.path.insert(0, str(BASE_DIR))

from src.scanner import (  # noqa: E402
    build_telegram_message,
    classify_risk_group,
    extract_top_sectors,
    fetch_evening_squeeze,
    fetch_morning_breakout,
    format_turnover_tl,
    safe_float,
    safe_str,
    send_telegram_notification,
)

# Ortam değişkenlerini yükle
load_dotenv(BASE_DIR / ".env")

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger("BISTMiniAppBackend")

TZ_TR = timezone(timedelta(hours=3))
FRONTEND_DIR = BASE_DIR / "frontend"

# Son taranan sonuçları bellekte önbellekle (Mini App açıldığında hızlı özet göstermek için)
SCAN_CACHE: Dict[str, Any] = {
    "last_updated": None,
    "scan_mode": None,
    "top_sectors": [],
    "stocks": [],
}

app = FastAPI(
    title="BIST Quant Scanner Mini App API",
    description="Borsa İstanbul Kantitatif Tarayıcı Telegram Mini App Backend Servisi",
    version="1.0.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ==============================================================================
# İSTEK MODELLERİ (Pydantic)
# ==============================================================================
class TriggerScanRequest(BaseModel):
    scan_mode: str = Field(
        default="morning_breakout",
        pattern="^(morning_breakout|evening_squeeze)$",
        description="Çalıştırılacak tarama modu: morning_breakout veya evening_squeeze",
    )
    run_direct_preview: bool = Field(
        default=True,
        description="GitHub Actions tetiklemesinin yanı sıra anlık özet sonuçları da döndürür",
    )
    notify_telegram: bool = Field(
        default=False,
        description="Anlık tarama yapılırken Telegram kanalına/sohbetine de mesaj gönderilsin mi?",
    )


# ==============================================================================
# YARDIMCI FONKSİYONLAR
# ==============================================================================
def verify_telegram_init_data(init_data: Optional[str], bot_token: str) -> bool:
    """
    Telegram WebApp initData imzasını doğrular (Opsiyonel güvenlik katmanı).
    Eğer init_data boşsa (tarayıcıdan lokal test yapılıyorsa) geçişe izin verir.
    """
    if not init_data or not bot_token:
        return True
    try:
        parsed_data = dict(parse_qsl(init_data, keep_blank_values=True))
        received_hash = parsed_data.pop("hash", None)
        if not received_hash:
            return False

        data_check_string = "\n".join(
            f"{k}={v}" for k, v in sorted(parsed_data.items())
        )
        secret_key = hmac.new(
            b"WebAppData", bot_token.encode("utf-8"), hashlib.sha256
        ).digest()
        calculated_hash = hmac.new(
            secret_key, data_check_string.encode("utf-8"), hashlib.sha256
        ).hexdigest()
        return hmac.compare_digest(calculated_hash, received_hash)
    except Exception as exc:
        logger.warning(f"Telegram initData doğrulama hatası: {exc}")
        return False


def dataframe_to_stock_cards(df: pd.DataFrame) -> List[Dict[str, Any]]:
    """Pandas DataFrame sonuçlarını Mini App arayüzündeki kartlara uygun JSON listesine dönüştürür."""
    if df is None or df.empty:
        return []

    cards: List[Dict[str, Any]] = []
    for rank, (_, row) in enumerate(df.iterrows(), start=1):
        symbol = safe_str(row.get("name"), default="BIST")
        close_price = safe_float(row.get("close"))
        change_pct = safe_float(row.get("change"))
        rel_vol = safe_float(row.get("relative_volume_10d_calc"))
        rsi_val = safe_float(row.get("RSI"))
        pivot_r1 = safe_float(row.get("Pivot.M.Classic.R1"))
        sector_name = safe_str(row.get("sector"), default="Belirtilmemiş")

        raw_value = row.get("Value.Traded")
        if raw_value is None or pd.isna(raw_value):
            raw_value = close_price * safe_float(row.get("volume"))

        risk_label = classify_risk_group(raw_value)
        turnover_str = format_turnover_tl(raw_value)

        close_pos_pct: Optional[float] = None
        if "close_position_ratio" in row and pd.notna(row.get("close_position_ratio")):
            close_pos_pct = round(safe_float(row.get("close_position_ratio")) * 100, 0)

        cards.append(
            {
                "rank": rank,
                "symbol": symbol,
                "close": round(close_price, 2),
                "change": round(change_pct, 2),
                "relative_volume": round(rel_vol, 2),
                "rsi": round(rsi_val, 1),
                "pivot_r1": round(pivot_r1, 2) if pivot_r1 > 0 else None,
                "sector": sector_name,
                "turnover_raw": safe_float(raw_value),
                "turnover_formatted": turnover_str,
                "risk_group": risk_label,
                "close_position_pct": close_pos_pct,
                "tradingview_url": f"https://tr.tradingview.com/chart/?symbol=BIST:{symbol}",
            }
        )
    return cards


def perform_live_scan(scan_mode: str, notify_telegram: bool = False) -> Dict[str, Any]:
    """TradingView üzerinden canlı tarama yapar ve SCAN_CACHE önbelleğini günceller."""
    df = (
        fetch_morning_breakout()
        if scan_mode == "morning_breakout"
        else fetch_evening_squeeze()
    )
    top_sectors = [
        {"sector": sec, "count": cnt}
        for sec, cnt in extract_top_sectors(df, top_n=2)
    ]
    stocks = dataframe_to_stock_cards(df)
    now_str = datetime.now(TZ_TR).strftime("%d.%m.%Y %H:%M:%S")

    SCAN_CACHE["last_updated"] = now_str
    SCAN_CACHE["scan_mode"] = scan_mode
    SCAN_CACHE["top_sectors"] = top_sectors
    SCAN_CACHE["stocks"] = stocks

    telegram_sent = False
    if notify_telegram:
        bot_token = os.environ.get("TELEGRAM_BOT_TOKEN", "").strip()
        chat_id = os.environ.get("TELEGRAM_CHAT_ID", "").strip()
        if bot_token and chat_id:
            msg = build_telegram_message(df, scan_mode)
            telegram_sent = send_telegram_notification(msg, bot_token, chat_id)

    return {
        "last_updated": now_str,
        "scan_mode": scan_mode,
        "total_count": len(stocks),
        "top_sectors": top_sectors,
        "stocks": stocks,
        "telegram_sent": telegram_sent,
    }


def trigger_github_workflow(scan_mode: str) -> Dict[str, Any]:
    """
    GitHub REST API üzerinden workflow_dispatch isteği gönderir:
    POST /repos/{owner}/{repo}/actions/workflows/{workflow_id}/dispatches
    """
    github_token = os.environ.get("GITHUB_TOKEN", "").strip()
    repo_owner = os.environ.get("REPO_OWNER", "uskom1").strip()
    repo_name = os.environ.get("REPO_NAME", "bist_bot").strip()
    workflow_id = os.environ.get("WORKFLOW_ID", "bist_scanner.yml").strip()
    git_ref = os.environ.get("GITHUB_REF", "main").strip()

    if not github_token:
        return {
            "dispatched": False,
            "reason": "GITHUB_TOKEN ortam değişkeni tanımlı değil (.env kontrol edin).",
            "repo": f"{repo_owner}/{repo_name}",
        }

    url = f"https://api.github.com/repos/{repo_owner}/{repo_name}/actions/workflows/{workflow_id}/dispatches"
    headers = {
        "Accept": "application/vnd.github+json",
        "Authorization": f"Bearer {github_token}",
        "X-GitHub-Api-Version": "2022-11-28",
    }
    payload = {
        "ref": git_ref,
        "inputs": {
            "scan_mode": scan_mode,
        },
    }

    try:
        resp = requests.post(url, headers=headers, json=payload, timeout=15)
        if resp.status_code == 204:
            logger.info(
                f"GitHub Actions workflow başarıyla tetiklendi: {repo_owner}/{repo_name} ({scan_mode})"
            )
            return {
                "dispatched": True,
                "message": "GitHub Actions iş akışı başarıyla kuyruğa alındı.",
                "repo": f"{repo_owner}/{repo_name}",
                "workflow": workflow_id,
                "ref": git_ref,
            }
        else:
            err_detail = resp.text[:300]
            logger.error(
                f"GitHub API Hatası (HTTP {resp.status_code}): {err_detail}"
            )
            return {
                "dispatched": False,
                "reason": f"GitHub API HTTP {resp.status_code} döndürdü: {err_detail}",
                "repo": f"{repo_owner}/{repo_name}",
            }
    except requests.exceptions.RequestException as exc:
        logger.error(f"GitHub API bağlantı hatası: {exc}")
        return {
            "dispatched": False,
            "reason": f"GitHub API bağlantı hatası: {exc}",
            "repo": f"{repo_owner}/{repo_name}",
        }


# ==============================================================================
# API UÇ NOKTALARI (ENDPOINTS)
# ==============================================================================
@app.get("/api/health")
def health_check() -> Dict[str, Any]:
    """Sunucu ve yapılandırma durumunu döndürür."""
    github_configured = bool(os.environ.get("GITHUB_TOKEN", "").strip())
    telegram_configured = bool(
        os.environ.get("TELEGRAM_BOT_TOKEN", "").strip()
        and os.environ.get("TELEGRAM_CHAT_ID", "").strip()
    )
    return {
        "status": "ok",
        "timestamp": datetime.now(TZ_TR).strftime("%d.%m.%Y %H:%M:%S"),
        "github_configured": github_configured,
        "telegram_configured": telegram_configured,
        "repo": f"{os.environ.get('REPO_OWNER', 'uskom1')}/{os.environ.get('REPO_NAME', 'bist_bot')}",
    }


@app.post("/api/trigger-scan")
def api_trigger_scan(
    request: TriggerScanRequest,
    x_telegram_init_data: Optional[str] = Header(default=None),
) -> JSONResponse:
    """
    1. GitHub Actions workflow_dispatch API'sini tetikler.
    2. Aynı zamanda Mini App ekranında sonuç kartlarının anında görünmesi için
       canlı tarama özetini çalıştırıp döndürür.
    """
    bot_token = os.environ.get("TELEGRAM_BOT_TOKEN", "").strip()
    if x_telegram_init_data and not verify_telegram_init_data(
        x_telegram_init_data, bot_token
    ):
        raise HTTPException(
            status_code=401, detail="Geçersiz Telegram WebApp imzası (initData)."
        )

    # 1. GitHub Actions Workflow Tetiklemesi
    gh_result = trigger_github_workflow(request.scan_mode)

    # 2. Canlı Tarama ve Kart Özeti
    scan_data: Optional[Dict[str, Any]] = None
    scan_error: Optional[str] = None
    if request.run_direct_preview:
        try:
            # Eğer GitHub Actions tetiklenemediyse (veya kullanıcı istediyse) Telegram bildirimini direkt gönder
            should_notify_tg = request.notify_telegram or (
                not gh_result.get("dispatched", False)
            )
            scan_data = perform_live_scan(
                request.scan_mode, notify_telegram=should_notify_tg
            )
        except Exception as exc:
            logger.exception(f"Canlı tarama hatası: {exc}")
            scan_error = str(exc)

    if not gh_result.get("dispatched") and scan_error:
        raise HTTPException(
            status_code=500,
            detail={
                "message": "Hem GitHub Actions tetiklemesi hem de canlı tarama başarısız oldu.",
                "github": gh_result,
                "scan_error": scan_error,
            },
        )

    return JSONResponse(
        content={
            "success": True,
            "scan_mode": request.scan_mode,
            "github_dispatch": gh_result,
            "scan_results": scan_data,
            "scan_error": scan_error,
        }
    )


@app.get("/api/results")
def api_get_results(
    scan_mode: str = "evening_squeeze",
    refresh: bool = False,
) -> Dict[str, Any]:
    """
    Son taranan hisselerin özetini döndürür.
    Eğer önbellek boşsa veya refresh=true ise TradingView'dan güncel veriyi çeker.
    """
    if scan_mode not in ("morning_breakout", "evening_squeeze"):
        scan_mode = "evening_squeeze"

    if (
        refresh
        or SCAN_CACHE["last_updated"] is None
        or SCAN_CACHE["scan_mode"] != scan_mode
    ):
        try:
            return perform_live_scan(scan_mode, notify_telegram=False)
        except Exception as exc:
            logger.error(f"Özet sonuç çekme hatası: {exc}")
            raise HTTPException(
                status_code=500, detail=f"TradingView verisi alınamadı: {exc}"
            )

    return {
        "last_updated": SCAN_CACHE["last_updated"],
        "scan_mode": SCAN_CACHE["scan_mode"],
        "total_count": len(SCAN_CACHE["stocks"]),
        "top_sectors": SCAN_CACHE["top_sectors"],
        "stocks": SCAN_CACHE["stocks"],
        "telegram_sent": False,
    }


@app.get("/api/workflow-runs")
def api_get_workflow_runs() -> Dict[str, Any]:
    """GitHub Actions üzerindeki son 5 çalışmanın durumunu döndürür."""
    github_token = os.environ.get("GITHUB_TOKEN", "").strip()
    repo_owner = os.environ.get("REPO_OWNER", "uskom1").strip()
    repo_name = os.environ.get("REPO_NAME", "bist_bot").strip()
    workflow_id = os.environ.get("WORKFLOW_ID", "bist_scanner.yml").strip()

    url = f"https://api.github.com/repos/{repo_owner}/{repo_name}/actions/workflows/{workflow_id}/runs?per_page=5"
    headers = {"Accept": "application/vnd.github+json"}
    if github_token:
        headers["Authorization"] = f"Bearer {github_token}"

    try:
        resp = requests.get(url, headers=headers, timeout=10)
        if resp.status_code != 200:
            return {"runs": [], "error": f"HTTP {resp.status_code}"}

        data = resp.json()
        runs = []
        for r in data.get("workflow_runs", [])[:5]:
            runs.append(
                {
                    "id": r.get("id"),
                    "status": r.get("status"),
                    "conclusion": r.get("conclusion"),
                    "event": r.get("event"),
                    "created_at": r.get("created_at"),
                    "html_url": r.get("html_url"),
                }
            )
        return {"runs": runs}
    except requests.exceptions.RequestException as exc:
        return {"runs": [], "error": str(exc)}


# ==============================================================================
# FRONTEND STATİK DOSYA SUNUMU
# ==============================================================================
@app.get("/")
def serve_mini_app() -> FileResponse:
    """Ana dizinde Telegram Mini App arayüzünü (frontend/index.html) sunar."""
    index_path = FRONTEND_DIR / "index.html"
    if not index_path.exists():
        raise HTTPException(
            status_code=404, detail="frontend/index.html dosyası bulunamadı."
        )
    return FileResponse(index_path)


if FRONTEND_DIR.exists():
    app.mount("/static", StaticFiles(directory=str(FRONTEND_DIR)), name="static")


if __name__ == "__main__":
    import uvicorn

    port = int(os.environ.get("PORT", "8000"))
    logger.info(f"BIST Quant Mini App Sunucusu başlatılıyor: http://0.0.0.0:{port}")
    uvicorn.run("backend.main:app", host="0.0.0.0", port=port, reload=True)

