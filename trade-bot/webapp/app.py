"""
NOAFVGBOT web paneli -- sadece yerel (localhost), basit Flask sunucusu.

Ne yapiyor:
- MT5 hesabindan (demo, XMGlobal-MT5 7) canli acik pozisyonlari ve son kapanan
  islemleri okur (MetaTrader5 Python paketi, zaten calisan terminale baglanir --
  ayri bir login/sifre gerektirmez).
- Proje kokunde ve results/ altinda biriken diagnostic/backtest JSON
  sonuclarini (module_diagnostic_*, h1_disable_*, ea_parity/*) listeler ve
  gosterir.
- Kullanicinin yazdigi serbest-metin feedback'i webapp/feedback_log.jsonl'a
  (append-only, zaman damgali) kaydeder -- OTOMATIK strateji degisikligi
  YAPMAZ, sadece kaydeder. Degisiklikler Claude tarafindan ayrica, elle,
  gerekirse holdout ile dogrulanarak uygulanir (kullanicinin tercih ettigi
  akis, bkz. proje sohbeti).

Calistirma: python webapp/app.py  (varsayilan port 5057, sadece 127.0.0.1)
"""

from __future__ import annotations

import glob
import json
import os
import sys
import time
from datetime import datetime, timezone

from flask import Flask, jsonify, render_template, request

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)  # strategy/config.py'yi dogrudan import edebilmek icin
FEEDBACK_LOG_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "feedback_log.jsonl")

# mql5/TradeBot_NOA_Recal.mq5 input MagicNumber varsayilani -- pozisyon/gecmis
# kayitlarinin BOTUN KENDI actigi mi yoksa harici/manuel mi oldugunu ayirt
# etmek icin (2026-09-04 gecesi yasanan karisikliktan sonra eklendi: USDTRY
# pozisyonu botla ilgisizdi ama magic ayrimi olmadan bunu anlamak zordu).
EA_MAGIC_NUMBERS = {20260903: "TradeBot_NOA_Recal", 20260826: "TradeBot_NOA_MultiSymbol (DEPRECATED)",
                    20260726: "TradeBot_NOA (DEPRECATED)"}
KEPT_SYMBOLS = ("GOLD", "BTCUSD", "EURGBP")

app = Flask(__name__)


def _ea_tag(magic: int) -> dict:
    name = EA_MAGIC_NUMBERS.get(magic)
    return {"is_ea_trade": name is not None, "ea_name": name}

# --- MT5 baglantisi (opsiyonel -- yuklu degilse/terminal kapaliysa panel yine calisir) ---
try:
    import MetaTrader5 as mt5
    _MT5_AVAILABLE = True
except ImportError:
    _MT5_AVAILABLE = False


def _mt5_call(fn):
    """MT5 cagrisini guvenli sekilde yapar -- baglanti yoksa/hata olursa None + hata mesaji doner."""
    if not _MT5_AVAILABLE:
        return None, "MetaTrader5 paketi yuklu degil"
    try:
        if not mt5.initialize():
            return None, f"mt5.initialize() basarisiz: {mt5.last_error()}"
        result = fn(mt5)
        return result, None
    except Exception as e:
        return None, f"{type(e).__name__}: {e}"


@app.route("/")
def index():
    return render_template("index.html")


@app.route("/positions")
def positions_page():
    return render_template("positions.html")


@app.route("/trades")
def trades_page():
    return render_template("trades.html")


@app.route("/risk")
def risk_page():
    return render_template("risk.html")


@app.route("/system-health")
def system_health_page():
    return render_template("system_health.html")


@app.route("/logs")
def logs_page():
    return render_template("logs.html")


@app.route("/backtest")
def backtest_page():
    return render_template("backtest.html")


# --- Market Research / Multi-Timeframe Scanner (scanner/ paketi -- CANLI
# arastirma, backtest DEGIL, bkz. scanner/__init__.py docstring'i). Tum
# sonuclar scanner/orchestrator.py:run_full_scan() tarafindan yazilan
# JSON dosyalarindan SADECE OKUNUR -- panel hicbir tarama mantigi
# calistirmiyor. ---
SCANNER_RESULTS_PATH = os.path.join(PROJECT_ROOT, "scanner_results.json")
SCANNER_CONFLUENCE_PATH = os.path.join(PROJECT_ROOT, "scanner_confluence.json")
SCANNER_CANDIDATES_PATH = os.path.join(PROJECT_ROOT, "scanner_candidates.json")
SCANNER_PROGRESS_PATH = os.path.join(PROJECT_ROOT, "scanner_progress.json")


def _read_json_file(path):
    if not os.path.exists(path):
        return None
    with open(path, "r", encoding="utf-8") as f:
        try:
            return json.load(f)
        except json.JSONDecodeError:
            return None


@app.route("/market-research")
def market_research_page():
    return render_template("market_research.html")


@app.route("/market-research/<symbol>")
def market_research_symbol_page(symbol):
    return render_template("market_research_symbol.html", symbol=symbol)


@app.route("/api/scanner/progress")
def api_scanner_progress():
    data = _read_json_file(SCANNER_PROGRESS_PATH)
    if data is None:
        return jsonify({"data": None, "error": "tarama henuz hic calistirilmadi"})
    return jsonify({"data": data, "error": None})


@app.route("/api/scanner/results")
def api_scanner_results():
    data = _read_json_file(SCANNER_RESULTS_PATH)
    if data is None:
        return jsonify({"data": {}, "error": "tarama sonucu yok"})
    return jsonify({"data": data, "error": None})


@app.route("/api/scanner/results/<symbol>")
def api_scanner_results_symbol(symbol):
    data = _read_json_file(SCANNER_RESULTS_PATH) or {}
    if symbol not in data:
        return jsonify({"data": None, "error": f"'{symbol}' icin tarama sonucu yok"})
    return jsonify({"data": data[symbol], "error": None})


@app.route("/api/scanner/confluence")
def api_scanner_confluence():
    data = _read_json_file(SCANNER_CONFLUENCE_PATH)
    if data is None:
        return jsonify({"data": {}, "error": "confluence sonucu yok"})
    return jsonify({"data": data, "error": None})


@app.route("/api/scanner/candidates")
def api_scanner_candidates():
    data = _read_json_file(SCANNER_CANDIDATES_PATH)
    if data is None:
        return jsonify({"data": [], "error": "aday listesi yok -- tarama tamamlanmamis olabilir"})
    return jsonify({"data": data, "error": None})


@app.route("/api/scanner/rescan/<symbol>/<tf>", methods=["POST"])
def api_scanner_rescan(symbol, tf):
    """Tek bir (sembol, timeframe) analizini CANLI olarak yeniden calistirir
    (bkz. proje talebi '23. HATA DURUMU -- [Retry]'). Sadece o hucreyi ve
    o sembolun confluence'ini gunceller, tum taramayi yeniden baslatmaz."""
    from dataclasses import asdict
    from scanner.timeframes import TIMEFRAMES
    from scanner.engine import analyze_symbol_timeframe, TimeframeResult
    from scanner.confluence import compute_confluence

    if tf not in TIMEFRAMES:
        return jsonify({"error": f"bilinmeyen zaman dilimi: {tf}"}), 400

    try:
        result = analyze_symbol_timeframe(symbol, tf)
    except Exception as e:
        return jsonify({"error": f"{type(e).__name__}: {e}"}), 500

    results = _read_json_file(SCANNER_RESULTS_PATH) or {}
    results.setdefault(symbol, {})[tf] = asdict(result)
    with open(SCANNER_RESULTS_PATH, "w", encoding="utf-8") as f:
        json.dump(results, f, ensure_ascii=False, default=str)

    tf_objs = {t: TimeframeResult(**d) for t, d in results[symbol].items()}
    conf = compute_confluence(symbol, tf_objs)
    confluence = _read_json_file(SCANNER_CONFLUENCE_PATH) or {}
    confluence[symbol] = asdict(conf)
    with open(SCANNER_CONFLUENCE_PATH, "w", encoding="utf-8") as f:
        json.dump(confluence, f, ensure_ascii=False, default=str)

    return jsonify({"data": asdict(result), "error": None})


COMMON_FILES_DIR = os.path.join(os.path.expanduser("~"), "AppData", "Roaming", "MetaQuotes", "Terminal", "Common", "Files")


@app.route("/api/pending")
def api_pending():
    """EA'nin su an bekleyen (henuz fiyata dokunmamis) sinyallerini
    NOA_Recal_pending_<SEMBOL>.csv dosyalarindan okur (bkz. mql5/TradeBot_
    NOA_Recal.mq5:WritePendingSnapshot). EA bir grafige eklenip calismiyorsa
    bu dosyalar hic olusmaz/eskir -- panel bunu acikca belirtir."""
    out = {}
    for symbol in KEPT_SYMBOLS:
        path = os.path.join(COMMON_FILES_DIR, f"NOA_Recal_pending_{symbol}.csv")
        if not os.path.exists(path):
            out[symbol] = {"available": False, "items": [], "updated": None}
            continue
        items = []
        with open(path, "r", encoding="utf-8-sig") as f:
            for line in f:
                parts = line.strip().split(";")
                if len(parts) < 6:
                    continue
                items.append({
                    "module": parts[0], "direction": parts[1],
                    "entry": float(parts[2]), "sl": float(parts[3]), "tp": float(parts[4]),
                    "signal_time": parts[5],
                })
        out[symbol] = {
            "available": True, "items": items,
            "updated": datetime.fromtimestamp(os.path.getmtime(path)).isoformat(),
        }
    return jsonify({"data": out})


@app.route("/api/config")
def api_config():
    return jsonify({"data": {
        "kept_symbols": list(KEPT_SYMBOLS),
        "ea_magic_numbers": EA_MAGIC_NUMBERS,
        "active_ea_magic": 20260903,
    }})


# --- Modul ornekleri (scratch_generate_module_examples.py'nin urettigi, GUNCEL
# resmi kalibrasyonla taze uretilmis kazanan/kaybeden/breakeven ornekleri) ---
MODULE_NAMES = {"fvg": "FVG", "ifvg": "iFVG", "ob": "Order Block", "trendline": "Trendline"}
MODULE_EXAMPLES_PATH = os.path.join(PROJECT_ROOT, "webapp", "data_module_examples.json")


@app.route("/module/<module_key>")
def module_page(module_key):
    if module_key not in MODULE_NAMES:
        return "bilinmeyen modul", 404
    return render_template("module.html", module_key=module_key, module_name=MODULE_NAMES[module_key],
                           all_modules=MODULE_NAMES)


@app.route("/api/examples/<module_key>")
def api_examples(module_key):
    if module_key not in MODULE_NAMES:
        return jsonify({"error": "bilinmeyen modul"}), 404
    if not os.path.exists(MODULE_EXAMPLES_PATH):
        return jsonify({"data": [], "error": "henuz uretilmedi -- scratch_generate_module_examples.py calistirilmali"})
    with open(MODULE_EXAMPLES_PATH, "r", encoding="utf-8") as f:
        all_examples = json.load(f)
    return jsonify({"data": all_examples.get(module_key, [])})


@app.route("/api/mt5/account")
def api_mt5_account():
    def _f(m):
        info = m.account_info()
        if info is None:
            return None
        return {
            "login": info.login, "server": info.server, "balance": info.balance,
            "equity": info.equity, "profit": info.profit, "currency": info.currency,
            "margin": info.margin, "margin_free": info.margin_free,
            "trade_expert_allowed": info.trade_expert,
        }
    data, err = _mt5_call(_f)
    return jsonify({"data": data, "error": err})


@app.route("/api/mt5/positions")
def api_mt5_positions():
    def _f(m):
        positions = m.positions_get()
        acc = m.account_info()
        balance = acc.balance if acc else 0.0
        out = []
        for p in (positions or []):
            row = {
                "ticket": p.ticket, "symbol": p.symbol,
                "type": "BUY" if p.type == 0 else "SELL",
                "volume": p.volume, "price_open": p.price_open,
                "sl": p.sl, "tp": p.tp, "price_current": p.price_current,
                "profit": p.profit, "comment": p.comment, "magic": p.magic,
                "time": datetime.fromtimestamp(p.time, tz=timezone.utc).isoformat(),
            }
            row.update(_ea_tag(p.magic))
            # Risk yuzdesi -- SL mesafesinden gercek $ riski (tick value/size
            # ile), EA'nin kendi CalcOpenPortfolioRiskPercent'iyle AYNI formul
            # (bkz. mql5/TradeBot_NOA_Recal.mq5). SL yoksa hesaplanamaz (None).
            row["risk_percent"] = None
            if p.sl and balance > 0:
                info = m.symbol_info(p.symbol)
                if info and info.trade_tick_size > 0:
                    sl_distance = abs(p.price_open - p.sl)
                    risk_amount = (sl_distance / info.trade_tick_size) * info.trade_tick_value * p.volume
                    row["risk_percent"] = round((risk_amount / balance) * 100, 3)
            out.append(row)
        return out
    data, err = _mt5_call(_f)
    return jsonify({"data": data, "error": err})


@app.route("/api/mt5/history")
def api_mt5_history():
    days = int(request.args.get("days", 30))
    def _f(m):
        from datetime import timedelta
        date_from = datetime.now(tz=timezone.utc) - timedelta(days=days)
        deals = m.history_deals_get(date_from, datetime.now(tz=timezone.utc))
        out = []
        for d in (deals or []):
            if d.entry != 1:  # sadece CIKIS deal'leri (entry=1 = DEAL_ENTRY_OUT) -- kapanan islemler
                continue
            row = {
                "ticket": d.ticket, "order": d.order, "symbol": d.symbol,
                "type": "BUY" if d.type == 0 else ("SELL" if d.type == 1 else str(d.type)),
                "volume": d.volume, "price": d.price, "profit": d.profit,
                "comment": d.comment, "magic": d.magic,
                "time": datetime.fromtimestamp(d.time, tz=timezone.utc).isoformat(),
            }
            row.update(_ea_tag(d.magic))
            out.append(row)
        out.sort(key=lambda x: x["time"], reverse=True)
        return out
    data, err = _mt5_call(_f)
    return jsonify({"data": data, "error": err})


@app.route("/api/mt5/equity_history")
def api_mt5_equity_history():
    """Kapanan islemlerden kumulatif P&L egrisi -- hem TUM hesap hem SADECE
    bot (bilinen magic) icin ayri seri. Gercek bir equity/balance gecmisi
    MT5 API'sinde yok, bu yuzden mevcut bakiyeden geriye dogru kapanan
    deal'lerin profit'ini cikararak/ekleyerek yeniden insa ediliyor."""
    days = int(request.args.get("days", 90))
    def _f(m):
        from datetime import timedelta
        date_from = datetime.now(tz=timezone.utc) - timedelta(days=days)
        deals = m.history_deals_get(date_from, datetime.now(tz=timezone.utc))
        closed = sorted(
            [d for d in (deals or []) if d.entry == 1],
            key=lambda d: d.time,
        )
        info = m.account_info()
        balance_now = info.balance if info else 0.0

        total_profit_in_window = sum(d.profit for d in closed)
        running_all = balance_now - total_profit_in_window
        running_bot = running_all  # bot-only serisi de ayni baslangictan, ama sadece kendi deal'leriyle ilerler
        # (mutlak deger degil, TREND onemli -- ikisi de ayni noktadan baslar,
        # bot-serisi sadece EA'nin katkisini izole eder)

        points_all = [{"time": date_from.isoformat(), "equity": round(running_all, 2)}]
        points_bot = [{"time": date_from.isoformat(), "equity": round(running_bot, 2)}]
        for d in closed:
            running_all += d.profit
            points_all.append({"time": datetime.fromtimestamp(d.time, tz=timezone.utc).isoformat(),
                               "equity": round(running_all, 2)})
            if d.magic in EA_MAGIC_NUMBERS:
                running_bot += d.profit
                points_bot.append({"time": datetime.fromtimestamp(d.time, tz=timezone.utc).isoformat(),
                                   "equity": round(running_bot, 2)})
        return {"all": points_all, "bot_only": points_bot, "currency": info.currency if info else "USD"}
    data, err = _mt5_call(_f)
    return jsonify({"data": data, "error": err})


# --- System health (mevcut endpoint'lerin toplu/agregat gorunumu -- yeni
# trading mantigi YOK, sadece zaten var olan MT5/pending-dosya kontrollerini
# tek bir yerde birlestiriyor) ---
@app.route("/api/system_health")
def api_system_health():
    def _f(m):
        acc = m.account_info()
        term = m.terminal_info()
        return {
            "mt5_connected": acc is not None,
            "account": {"login": acc.login, "server": acc.server, "balance": acc.balance} if acc else None,
            "terminal": {"connected": term.connected, "trade_allowed": term.trade_allowed} if term else None,
        }
    mt5_data, mt5_err = _mt5_call(_f)

    pending_ages = {}
    any_pending_available = False
    for symbol in KEPT_SYMBOLS:
        path = os.path.join(COMMON_FILES_DIR, f"NOA_Recal_pending_{symbol}.csv")
        if os.path.exists(path):
            any_pending_available = True
            pending_ages[symbol] = (time.time() - os.path.getmtime(path))
        else:
            pending_ages[symbol] = None

    newest_age = min([a for a in pending_ages.values() if a is not None], default=None)

    return jsonify({"data": {
        "mt5": mt5_data, "mt5_error": mt5_err,
        "bot_active": any_pending_available,
        "pending_ages_seconds": pending_ages,
        "data_fresh": (newest_age is not None and newest_age < 600),
        "server_time": datetime.now(tz=timezone.utc).isoformat(),
    }})


# --- Loglar (MT5 terminalinin kendi Experts/Journal log dosyasini SADECE
# OKUR -- read-only tail, hicbir trading davranisi degismiyor) ---
LOG_LEVEL_TAGS = {
    "ERROR": ("[ORDER_SEND_FAILED]", "[MARGIN_CALC_FAILED]", "[INSUFFICIENT_MARGIN]", "[INVALID_SL]", "[INVALID_VOLUME]"),
    "WARNING": ("[STOP_LEVEL_TOO_CLOSE]", "[MAX_LOT_GUARD]", "[PORTFOLIO_RISK_CAP]", "[EXISTING_EA_POSITION]", "lost", "failed", "rejected"),
    "SUCCESS": ("[TRADE_OPENED]",),
}


def _classify_log_level(raw_level: str, message: str) -> str:
    msg_lower = message.lower()
    for level, needles in LOG_LEVEL_TAGS.items():
        for needle in needles:
            if needle.lower() in msg_lower:
                return level
    # MT5'in kendi seviye kodu: 1/2 genelde uyari/hata (Experts log'unda
    # gozlemlendi -- Network baglanti kopmalari "1" ile isaretleniyor)
    if raw_level == "1":
        return "WARNING"
    if raw_level == "2":
        return "ERROR"
    return "INFO"


@app.route("/api/logs")
def api_logs():
    n = int(request.args.get("n", 400))

    def _f(m):
        term = m.terminal_info()
        return term.data_path if term else None
    data_path, err = _mt5_call(_f)
    if not data_path:
        return jsonify({"data": [], "error": err or "MT5 terminal data_path alinamadi"})

    logs_dir = os.path.join(data_path, "MQL5", "Logs")
    today = datetime.now().strftime("%Y%m%d")
    log_path = os.path.join(logs_dir, f"{today}.log")
    if not os.path.exists(log_path):
        # Bugun henuz hicbir MT5 aktivitesi olmadiysa gunun log dosyasi hic
        # olusmaz -- "veri yok" gostermek yerine en son mevcut gune duser
        # (gercek bir terminal/Journal goruntuleyicisinin yapacagi gibi).
        existing = sorted(glob.glob(os.path.join(logs_dir, "*.log")))
        if not existing:
            return jsonify({"data": [], "error": f"hic log dosyasi bulunamadi: {logs_dir}"})
        log_path = existing[-1]

    try:
        with open(log_path, "r", encoding="utf-16-le", errors="ignore") as f:
            lines = f.readlines()
    except Exception as e:
        return jsonify({"data": [], "error": f"log okunamadi: {e}"})

    out = []
    for line in lines[-n:]:
        parts = line.rstrip("\r\n").split("\t")
        if len(parts) < 5:
            continue
        _id, raw_level, log_time, source, message = parts[0], parts[1], parts[2], parts[3], "\t".join(parts[4:])
        out.append({
            "time": log_time, "source": source, "message": message,
            "level": _classify_log_level(raw_level, message),
        })
    log_date = os.path.basename(log_path).replace(".log", "")
    return jsonify({"data": out, "error": None, "log_date": log_date, "is_today": log_date == today})


# --- Diagnostic/backtest JSON sonuclari ---
DIAGNOSTIC_FILES = [
    ("module_diagnostic_full_universe_results.json", "Tam evren tarama (101 sembol, modul+portfoy)"),
    ("module_diagnostic_full_scan_results.json", "KEPT_SYMBOLS derin tarama (GOLD/BTCUSD/EURGBP)"),
    ("h1_disable_walkforward_results.json", "H1 zaman dilimi walk-forward (6 fold x 3 sembol)"),
    ("h1_disable_holdout_check_results.json", "H1 zaman dilimi tek-holdout kontrolu"),
]


@app.route("/api/diagnostics/list")
def api_diagnostics_list():
    out = []
    for filename, desc in DIAGNOSTIC_FILES:
        path = os.path.join(PROJECT_ROOT, filename)
        if os.path.exists(path):
            stat = os.stat(path)
            out.append({
                "name": filename, "description": desc,
                "size_bytes": stat.st_size,
                "modified": datetime.fromtimestamp(stat.st_mtime).isoformat(),
            })
    ea_parity_dir = os.path.join(PROJECT_ROOT, "results", "ea_parity")
    if os.path.isdir(ea_parity_dir):
        for p in sorted(glob.glob(os.path.join(ea_parity_dir, "*.json"))):
            stat = os.stat(p)
            out.append({
                "name": "ea_parity/" + os.path.basename(p),
                "description": "EA<->Python parite -- " + os.path.basename(p).replace("_python_signals.json", ""),
                "size_bytes": stat.st_size,
                "modified": datetime.fromtimestamp(stat.st_mtime).isoformat(),
            })
    return jsonify({"data": out})


@app.route("/api/diagnostics/<path:name>")
def api_diagnostics_get(name):
    safe_path = os.path.normpath(os.path.join(PROJECT_ROOT, name))
    if not safe_path.startswith(PROJECT_ROOT) or not os.path.exists(safe_path):
        return jsonify({"error": "bulunamadi"}), 404
    with open(safe_path, "r", encoding="utf-8") as f:
        try:
            content = json.load(f)
        except json.JSONDecodeError:
            return jsonify({"error": "gecersiz/yariminda JSON (tarama hala yaziyor olabilir)"}), 200
    return jsonify({"data": content})


# --- Feedback ---
@app.route("/api/feedback", methods=["GET"])
def api_feedback_list():
    entries = []
    if os.path.exists(FEEDBACK_LOG_PATH):
        with open(FEEDBACK_LOG_PATH, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line:
                    entries.append(json.loads(line))
    entries.sort(key=lambda e: e["timestamp"], reverse=True)
    return jsonify({"data": entries})


@app.route("/api/feedback", methods=["POST"])
def api_feedback_post():
    body = request.get_json(force=True, silent=True) or {}
    text = (body.get("text") or "").strip()
    if not text:
        return jsonify({"error": "bos feedback kaydedilmez"}), 400

    entry = {
        "id": int(time.time() * 1000),
        "timestamp": datetime.now(tz=timezone.utc).isoformat(),
        "text": text,
        "status": "yeni",  # yeni | incelendi | uygulandi | reddedildi -- Claude ileride gunceller
    }
    # Ornek-bazli feedback ise (module sayfasindan) hangi ornege referans
    # verdigini de sakla -- Claude ileride bu context'i okuyabilsin diye.
    context = body.get("context")
    if context:
        entry["context"] = context
    with open(FEEDBACK_LOG_PATH, "a", encoding="utf-8") as f:
        f.write(json.dumps(entry, ensure_ascii=False) + "\n")
    return jsonify({"data": entry})


VALID_FEEDBACK_STATUSES = {"yeni", "incelendi", "uygulandi", "reddedildi"}


@app.route("/api/feedback/<int:feedback_id>", methods=["PATCH"])
def api_feedback_update(feedback_id):
    """Feedback'in durumunu (ve istege bagli bir admin notunu) gunceller --
    dosyayi baştan okuyup ilgili satiri degistirip yeniden yazar (jsonl kucuk
    oldugu icin bu basit yaklasim yeterli, ayri bir DB gerekmiyor)."""
    body = request.get_json(force=True, silent=True) or {}
    new_status = body.get("status")
    admin_note = body.get("admin_note")
    if new_status is not None and new_status not in VALID_FEEDBACK_STATUSES:
        return jsonify({"error": f"gecersiz durum: {new_status}"}), 400

    if not os.path.exists(FEEDBACK_LOG_PATH):
        return jsonify({"error": "bulunamadi"}), 404

    entries = []
    found = None
    with open(FEEDBACK_LOG_PATH, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            e = json.loads(line)
            if e["id"] == feedback_id:
                if new_status is not None:
                    e["status"] = new_status
                if admin_note is not None:
                    e["admin_note"] = admin_note
                e["reviewed_at"] = datetime.now(tz=timezone.utc).isoformat()
                found = e
            entries.append(e)

    if found is None:
        return jsonify({"error": "bulunamadi"}), 404

    with open(FEEDBACK_LOG_PATH, "w", encoding="utf-8") as f:
        for e in entries:
            f.write(json.dumps(e, ensure_ascii=False) + "\n")

    return jsonify({"data": found})


@app.route("/feedback")
def feedback_page():
    return render_template("feedback.html")


# --- Strateji parametreleri (dogrudan strategy/config.py'den, tek kaynak --
# panel hicbir degeri KENDI tutmuyor, repo neyse onu gosterir) ---
@app.route("/config")
def config_page():
    return render_template("config.html")


@app.route("/api/strategy_config")
def api_strategy_config():
    import importlib
    import strategy.config as sc
    importlib.reload(sc)  # dosya degismis olabilir, her istekte taze oku
    dc = sc.DEFAULT_CONFIG
    return jsonify({"data": {
        "kept_symbols": list(sc.KEPT_SYMBOLS),
        "excluded_symbols_count": len(sc.EXCLUDED_SYMBOLS),
        "module_r_multiple": sc.MODULE_R_MULTIPLE,
        "module_sl_buffer_ratio": sc.MODULE_SL_BUFFER_RATIO,
        "module_disabled_timeframes": sc.MODULE_DISABLED_TIMEFRAMES,
        "breakeven_trigger_pct": sc.BREAKEVEN_TRIGGER_PCT,
        "breakeven_enabled_modules": list(sc.BREAKEVEN_ENABLED_MODULES),
        "default_config": {
            "atr_period": dc.atr_period,
            "min_gap_to_atr_ratio": dc.min_gap_to_atr_ratio,
            "max_gap_to_atr_ratio": dc.max_gap_to_atr_ratio,
            "max_middle_candle_ratio": dc.max_middle_candle_ratio,
            "avg_range_period": dc.avg_range_period,
            "strong_move_ratio": dc.strong_move_ratio,
            "volume_confirm_period": dc.volume_confirm_period,
            "volume_confirm_ratio": dc.volume_confirm_ratio,
            "swing_lookback": dc.swing_lookback,
            "tolerance_atr_ratio": dc.tolerance_atr_ratio,
            "min_level_touch_count": dc.min_level_touch_count,
            "trendline_swing_lookback": dc.trendline_swing_lookback,
            "trendline_min_touches": dc.trendline_min_touches,
            "trendline_touch_tolerance_atr_ratio": dc.trendline_touch_tolerance_atr_ratio,
        },
    }})


if __name__ == "__main__":
    print(f"NOAFVGBOT web paneli: http://127.0.0.1:5057")
    app.run(host="127.0.0.1", port=5057, debug=False)
