"""Модуль импорта и детального анализа сделок и портфелей инвестора.

Поддерживает:
1. Прямой импорт из сервиса учёта инвестиций izi-invest.ru (по ссылке или username/ID).
2. Загрузку и парсинг брокерских отчётов (T-Банк, Сбер, ВТБ, Альфа, БКС, Snowball, Intelinvest, CSV).
3. Расчёт фактической средней цены входа (Break-even), нереализованного и реализованного PnL.
4. Расчёт XIRR (Money-Weighted Return) и построение зеркального бенчмарка IMOEX.
5. Анализ закрытых сделок по методу FIFO и статистику пассивного денежного потока (дивиденды и купоны).
"""

from __future__ import annotations

import io
import re
from datetime import datetime, date
from typing import Any, Dict, List, Optional, Tuple, Union

import numpy as np
import pandas as pd
import requests

try:
    from moexalgo import Ticker
except ImportError:
    Ticker = None


# Безопасный лимит размера файла брокерского отчета (DoS/OOM защита)
MAX_FILE_SIZE_BYTES = 25 * 1024 * 1024  # 25 МБ

# Известные сплиты и консолидации акций на MOEX
# format: {ticker: [(split_date, ratio)]}
# ratio: во сколько раз изменилось количество акций
# TRNFP: 1:100 сплит 14.02.2024 (1 старая акция -> 100 новых)
# VTBR: 5000:1 консолидация 09.07.2024 (5000 старых акций -> 1 новая)
STOCK_SPLITS: Dict[str, List[Tuple[pd.Timestamp, float]]] = {
    "TRNFP": [(pd.to_datetime("2024-02-14"), 100.0)],
    "VTBR": [(pd.to_datetime("2024-07-09"), 1.0 / 5000.0)],
}

def adjust_trade_for_splits(ticker: str, trade_date: pd.Timestamp, qty: float, price: float) -> Tuple[float, float]:
    """
    Корректирует историческое количество и цену сделки под сплиты акций,
    сохраняя исходную сумму инвестиций (qty * price).
    """
    splits = STOCK_SPLITS.get(ticker.upper())
    if not splits:
        return qty, price

    adj_qty = qty
    adj_price = price
    t_dt = pd.to_datetime(trade_date).tz_localize(None) if hasattr(trade_date, "tz_localize") else pd.to_datetime(trade_date)

    for split_date, mult in splits:
        s_dt = pd.to_datetime(split_date).tz_localize(None)
        if t_dt < s_dt:
            adj_qty = adj_qty * mult
            adj_price = adj_price / mult if mult != 0 else adj_price

    return adj_qty, adj_price


def get_moex_fx_rates() -> Dict[str, float]:
    """Загружает актуальные биржевые курсы валют (USD, EUR, CNY) с MOEX ISS."""
    rates = {"RUB": 1.0, "RUR": 1.0, "SUR": 1.0, "CNY": 12.52, "USD": 85.0, "EUR": 100.0}
    try:
        url_rates = "https://iss.moex.com/iss/engines/currency/markets/selt/boards/CETS/securities.json"
        resp = requests.get(
            url_rates,
            params={"iss.meta": "off", "iss.only": "marketdata", "marketdata.columns": "SECID,LAST"},
            timeout=5
        ).json()
        for row in resp.get("marketdata", {}).get("data", []):
            secid = str(row[0] or "")
            last = row[1]
            if last and float(last) > 0:
                if secid == "CNYRUB_TOM":
                    rates["CNY"] = float(last)
                elif secid == "USD000UTSTOM":
                    rates["USD"] = float(last)
                elif secid == "EUR_RUB__TOM":
                    rates["EUR"] = float(last)
    except Exception:
        pass
    return rates


def get_bond_rub_valuation(
    ticker: str,
    raw_price: float,
    nominal: float = 1000.0,
    nkd: float = 0.0,
    currency: str = "RUB",
    fx_rates: Optional[Dict[str, float]] = None
) -> float:
    """
    Рассчитывает реальную рублевую стоимость одной облигации.
    На Мосбирже котировка облигации raw_price указывается в % от номинала (Face Value).
    Грязная цена (с накопленным купоном НКД) в валюте = (raw_price / 100) * nominal + nkd.
    Итоговая стоимость одной облигации в рублях = Грязная цена * Курс валюты к рублю.
    """
    if fx_rates is None:
        fx_rates = get_moex_fx_rates()

    curr = str(currency or "RUB").strip().upper()
    if curr in ["RUR", "SUR"]:
        curr = "RUB"

    fx = fx_rates.get(curr, 1.0)

    # Если цена уже в рублях (например, больше 500 рублей за штуку)
    if raw_price > 500.0:
        return raw_price

    nom = float(nominal if nominal > 0 else 1000.0)
    clean_curr = (raw_price / 100.0) * nom
    dirty_curr = clean_curr + float(nkd or 0.0)
    return dirty_curr * fx


# ==========================================
# 1. МАТЕМАТИЧЕСКИЕ АЛГОРИТМЫ (XIRR & БЕНЧМАРКИ)
# ==========================================

def calculate_xirr(cashflows: List[Tuple[Union[datetime, date], float]]) -> float:
    """
    Рассчитывает XIRR (Internal Rate of Return) для неравномерных денежных потоков.
    Входные данные: список кортежей (дата, сумма).
    Отрицательные суммы — пополнения счета (инвестиции).
    Положительные суммы — выводы средств и итоговая оценка портфеля на текущий момент.
    """
    if len(cashflows) < 2:
        return 0.0

    valid_flows = []
    for d, amt in cashflows:
        if pd.isna(amt) or abs(amt) < 1e-6:
            continue
        valid_flows.append((pd.to_datetime(d), float(amt)))

    if len(valid_flows) < 2:
        return 0.0

    dates = [cf[0] for cf in valid_flows]
    amounts = [cf[1] for cf in valid_flows]

    # Должен быть хотя бы один приток и хотя бы один отток денег
    has_positive = any(a > 0 for a in amounts)
    has_negative = any(a < 0 for a in amounts)
    if not (has_positive and has_negative):
        return 0.0

    d0 = min(dates)
    days = np.array([(d - d0).days for d in dates], dtype=float)
    amts = np.array(amounts, dtype=float)

    def npv(r: float) -> float:
        if r <= -1.0:
            return float("inf")
        # NPV = sum(CF_i / (1 + r)^(t_i / 365.25))
        discount = (1.0 + r) ** (days / 365.25)
        return float(np.sum(amts / discount))

    # Метод бисекции (дихотомии) с широкими границами доходности
    low = -0.99
    high = 10.0  # до 1000% годовых
    v_low = npv(low)
    v_high = npv(high)

    if v_low * v_high > 0:
        # Проверяем расширенный диапазон
        high = 50.0
        v_high = npv(high)
        if v_low * v_high > 0:
            return 0.0

    for _ in range(120):
        mid = (low + high) / 2.0
        val = npv(mid)
        if abs(val) < 1e-4:
            return round(mid * 100.0, 2)
        if v_low * val < 0:
            high = mid
            v_high = val
        else:
            low = mid
            v_low = val

    return round(((low + high) / 2.0) * 100.0, 2)


# ==========================================
# 2. ПАРСИНГ IZI-INVEST.RU
# ==========================================

def resolve_izi_invest_portfolio_id(identifier: str) -> Optional[int]:
    """
    Извлекает числовой portfolio_id из URL, username или строки ID.
    Примеры:
    - 'https://izi-invest.ru/maxgamer#sdelki' -> 47933
    - 'maxgamer' -> 47933
    - '47933' -> 47933
    """
    clean_id = identifier.strip()

    # Если уже число
    if clean_id.isdigit():
        return int(clean_id)

    # Если ссылка или слаг
    match = re.search(r"izi-invest\.ru/([a-zA-Z0-9_\-\.]+)", clean_id)
    if match:
        slug = match.group(1)
    else:
        # Предполагаем, что введен просто slug (например, 'maxgamer')
        slug = clean_id.split("#")[0].split("?")[0].strip()

    # Защита от SSRF / Path Traversal: slug должен содержать только безопасные алфавитно-цифровые символы
    if not re.match(r"^[a-zA-Z0-9_\-\.]+$", slug):
        return None

    url = f"https://izi-invest.ru/{slug}"
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8"
    }
    html_text = ""
    try:
        import httpx
        # follow_redirects=False для защиты от SSRF перенаправлений на метаданные облака или внутренние IP
        with httpx.Client(headers=headers, follow_redirects=False, timeout=12.0) as client:
            resp = client.get(url)
            if resp.status_code == 200:
                html_text = resp.text
            elif resp.status_code in (301, 302, 307, 308):
                loc = resp.headers.get("Location", "")
                if loc.startswith("/") or loc.startswith("https://izi-invest.ru/"):
                    safe_url = loc if loc.startswith("https://") else f"https://izi-invest.ru{loc}"
                    resp2 = client.get(safe_url)
                    if resp2.status_code == 200:
                        html_text = resp2.text
    except Exception:
        pass

    if not html_text:
        try:
            resp = requests.get(url, headers=headers, allow_redirects=False, timeout=12)
            if resp.status_code == 200:
                html_text = resp.text
            elif resp.status_code in (301, 302):
                loc = resp.headers.get("Location", "")
                if loc.startswith("/") or loc.startswith("https://izi-invest.ru/"):
                    safe_url = loc if loc.startswith("https://") else f"https://izi-invest.ru{loc}"
                    resp2 = requests.get(safe_url, headers=headers, allow_redirects=False, timeout=12)
                    if resp2.status_code == 200:
                        html_text = resp2.text
        except Exception:
            pass

    if html_text:
        id_match = re.search(r"portfolio_id\s*=\s*(\d+)", html_text)
        if id_match:
            return int(id_match.group(1))

    return None


def fetch_izi_invest_data(identifier: str) -> Dict[str, Any]:
    """
    Загружает полный дамп портфеля из izi-invest.ru и парсит все вкладки.
    """
    pid = resolve_izi_invest_portfolio_id(identifier)
    if not pid:
        raise ValueError(f"Не удалось определить ID портфеля для '{identifier}'. Убедитесь, что портфель открыт для публичного доступа.")

    export_url = f"https://izi-invest.ru/calc/?portfolio={pid}&export=1"
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
    }

    content_bytes = b""
    try:
        import httpx
        with httpx.Client(headers=headers, follow_redirects=True, timeout=25.0) as client:
            resp = client.get(export_url)
            if resp.status_code == 200 and len(resp.content) > 1000:
                content_bytes = resp.content
    except Exception:
        pass

    if not content_bytes:
        resp = requests.get(export_url, headers=headers, timeout=25)
        if resp.status_code != 200 or len(resp.content) < 1000:
            raise ConnectionError(f"Ошибка получения экспорта izi-invest (код {resp.status_code}, длина ответа {len(resp.content)} байт).")
        content_bytes = resp.content

    return parse_izi_invest_excel(content_bytes, source_id=str(pid), identifier=identifier)


def _find_sheet(sheet_names: List[str], keywords: List[str]) -> Optional[str]:
    """Находит подходящий лист по ключевым словам без учета регистра."""
    for s in sheet_names:
        sl = str(s).strip().lower()
        for kw in keywords:
            if kw in sl:
                return s
    return None


def reconstruct_positions_from_trades(trades_df: pd.DataFrame) -> pd.DataFrame:
    """
    Восстанавливает текущие открытые позиции инвестора и среднюю цену входа (Break-even)
    из хронологического журнала сделок купли/продажи.
    """
    if trades_df.empty or "Операция" not in trades_df.columns:
        return pd.DataFrame()

    trades = trades_df.copy()
    trades["Дата"] = pd.to_datetime(trades["Дата"])
    trades = trades.sort_values(by="Дата")

    holdings = {}
    for _, row in trades.iterrows():
        t = str(row.get("Тикер", "")).strip().upper()
        if not t or t in ["NAN", "NONE", "INPUT", "OUTPUT", "DOHOD", "NALOG", "COMMISSION"]:
            continue
        trade_date = pd.to_datetime(row.get("Дата"))
        name = str(row.get("Название", t))
        atype = str(row.get("Тип", "share")).lower()
        curr = str(row.get("Валюта", "RUB")).upper()
        fx_rates = get_moex_fx_rates()
        fx = fx_rates.get(curr, 1.0)
        is_bond = atype in ["bond", "облигация"] or t.startswith(("RU000", "SU", "XS"))

        qty = abs(float(row.get("Количество", 0.0)))
        price = float(row.get("Цена", 0.0))
        cost = abs(float(row.get("Сумма", 0.0)))

        if is_bond:
            if curr in ["CNY", "USD", "EUR"]:
                cost = cost * fx
            price_rub = get_bond_rub_valuation(t, price, 1000.0, 0.0, curr, fx_rates)
        else:
            # Корректировка на корпоративные сплиты (TRNFP 1:100, VTBR 1:5000)
            qty, price = adjust_trade_for_splits(t, trade_date, qty, price)
            price_rub = price

        if cost == 0.0 and price_rub > 0:
            cost = qty * price_rub

        op = str(row.get("Операция", "")).lower()
        is_buy = any(b in op for b in ["buy", "покупка", "приобретение"])
        is_sell = any(s in op for s in ["sell", "продажа", "списание"])

        if t not in holdings:
            holdings[t] = {"qty": 0.0, "total_cost": 0.0, "name": name, "type": atype, "last_price": price_rub}

        if is_buy:
            holdings[t]["qty"] += qty
            holdings[t]["total_cost"] += cost
            if price_rub > 0:
                holdings[t]["last_price"] = price_rub
        elif is_sell:
            curr_q = holdings[t]["qty"]
            if curr_q > 0:
                avg_p = holdings[t]["total_cost"] / curr_q
                sold_q = min(qty, curr_q)
                holdings[t]["qty"] -= sold_q
                holdings[t]["total_cost"] = max(0.0, holdings[t]["total_cost"] - sold_q * avg_p)
            if price_rub > 0:
                holdings[t]["last_price"] = price_rub

    rows = []
    for t, data in holdings.items():
        if data["qty"] > 0.001:
            avg_p = data["total_cost"] / data["qty"] if data["qty"] > 0 else 0.0
            cur_price = data["last_price"]
            # Попытка получить свежую цену с MOEX если доступно
            if Ticker is not None and data["type"] == "share":
                try:
                    asset = Ticker(t)
                    c = asset.candles(date=str(datetime.now().date() - pd.Timedelta(days=5)), till_date=str(datetime.now().date()), period="D")
                    if c is not None and not c.empty and "close" in c.columns:
                        cur_price = float(c["close"].iloc[-1])
                except Exception:
                    pass

            cur_val = data["qty"] * cur_price
            pnl = cur_val - data["total_cost"]
            pnl_pct = (pnl / data["total_cost"] * 100.0) if data["total_cost"] > 0 else 0.0

            rows.append({
                "Тикер": t,
                "Название": data["name"],
                "Тип": data["type"],
                "Количество": round(data["qty"], 2),
                "Средняя цена": round(avg_p, 2),
                "Текущая цена": round(cur_price, 2),
                "Вложенная сумма": round(data["total_cost"], 2),
                "Текущая стоимость": round(cur_val, 2),
                "Прибыль, ₽": round(pnl, 2),
                "Доходность от входа, %": round(pnl_pct, 2)
            })

    res_df = pd.DataFrame(rows)
    if not res_df.empty:
        tot_v = res_df["Текущая стоимость"].sum()
        res_df["Вес, %"] = (res_df["Текущая стоимость"] / tot_v * 100.0) if tot_v > 0 else 0.0
        res_df = res_df.sort_values(by="Текущая стоимость", ascending=False).reset_index(drop=True)
    return res_df


def parse_izi_invest_excel(file_bytes: bytes, source_id: str = "export", identifier: str = "") -> Dict[str, Any]:
    """
    Парсит XLSX файл из izi-invest, Intelinvest, Snowball или отчётов брокеров.
    Автоматически сопоставляет вкладки и восстанавливает позиции, если вкладка отсутствует.
    """
    if len(file_bytes) > MAX_FILE_SIZE_BYTES:
        raise ValueError(
            f"Файл слишком большой ({len(file_bytes) / (1024 * 1024):.1f} МБ). "
            f"Максимальный допустимый размер для защиты сервера — {MAX_FILE_SIZE_BYTES // (1024 * 1024)} МБ."
        )

    xls = pd.ExcelFile(io.BytesIO(file_bytes))
    sheet_names = xls.sheet_names

    sheet_pos = _find_sheet(sheet_names, ["портфел", "position", "holding", "актив"])
    sheet_trades = _find_sheet(sheet_names, ["сделк", "trade", "deal", "operation", "операци", "транзакци"])
    sheet_div = _find_sheet(sheet_names, ["дивиденд", "div"])
    sheet_coup = _find_sheet(sheet_names, ["купон", "coupon"])
    sheet_fifo = _find_sheet(sheet_names, ["fifo", "закрыт", "closed"])
    sheet_xirr = _find_sheet(sheet_names, ["xirr"])

    # Если лист сделок не найден по названию, проверяем колонки первого или всех листов
    if not sheet_trades:
        for s in sheet_names:
            try:
                head_df = pd.read_excel(xls, s, nrows=5)
                cols_l = [str(c).lower() for c in head_df.columns]
                if any("дат" in c or "date" in c for c in cols_l) and any("тикер" in c or "ticker" in c or "инструмент" in c for c in cols_l):
                    sheet_trades = s
                    break
            except Exception:
                continue

    # 1. Парсинг сделок
    trades_df = pd.DataFrame()
    if sheet_trades:
        raw_trades = pd.read_excel(xls, sheet_trades)
        # Находим колонку даты и тикера
        date_col = next((c for c in raw_trades.columns if any(k in str(c).lower() for k in ["дат", "date"])), None)
        ticker_col = next((c for c in raw_trades.columns if any(k in str(c).lower() for k in ["тикер", "ticker", "secid", "инструмент", "код"])), None)
        
        if date_col and ticker_col:
            t_df = raw_trades.dropna(subset=[date_col]).copy()
            t_df["Дата"] = pd.to_datetime(t_df[date_col])
            t_df["Тикер"] = t_df[ticker_col].astype(str).str.strip().str.upper()

            # Нормализация колонок
            for c in raw_trades.columns:
                cl = str(c).lower().strip()
                if "unnamed" in cl:
                    continue
                if any(k in cl for k in ["количеств", "кол", "qty"]):
                    t_df["Количество"] = pd.to_numeric(raw_trades[c], errors="coerce").fillna(0.0)
                elif any(k in cl for k in ["цен", "price"]):
                    t_df["Цена"] = pd.to_numeric(raw_trades[c], errors="coerce").fillna(0.0)
                elif any(k in cl for k in ["сумм", "объем", "sum", "volume"]):
                    t_df["Сумма"] = pd.to_numeric(raw_trades[c], errors="coerce").fillna(0.0)
                elif any(k in cl for k in ["операц", "action", "вид сделки", "direction"]):
                    t_df["Операция"] = raw_trades[c].astype(str).str.lower()
                elif cl in ["тип", "type", "вид актива", "asset_type"]:
                    t_df["Тип"] = raw_trades[c].astype(str).str.lower()
                elif any(k in cl for k in ["валют", "curr"]):
                    t_df["Валюта"] = raw_trades[c].astype(str).str.upper()
                elif any(k in cl for k in ["назван", "наименов", "эмитент"]) or cl == "name":
                    t_df["Название"] = raw_trades[c].astype(str)

            if "Операция" not in t_df.columns:
                t_df["Операция"] = "buy"
            if "Количество" not in t_df.columns:
                t_df["Количество"] = 0.0
            if "Цена" not in t_df.columns:
                t_df["Цена"] = 0.0
            if "Сумма" not in t_df.columns:
                t_df["Сумма"] = t_df["Количество"] * t_df["Цена"]

            bank_fee = t_df.get("Комиссия банка", pd.Series(0.0, index=t_df.index))
            ts_fee = t_df.get("Комиссия ТС", pd.Series(0.0, index=t_df.index))
            t_df["Комиссия, ₽"] = (pd.to_numeric(bank_fee, errors="coerce").fillna(0.0).abs() + pd.to_numeric(ts_fee, errors="coerce").fillna(0.0).abs()).round(2)

            trades_df = t_df.sort_values(by="Дата", ascending=False).reset_index(drop=True)

    # 2. Парсинг открытых позиций
    positions_df = pd.DataFrame()
    if sheet_pos:
        raw_port = pd.read_excel(xls, sheet_pos)
        ticker_col = next((c for c in raw_port.columns if any(k in str(c).lower() for k in ["тикер", "ticker", "secid"])), None)
        if ticker_col:
            p_df = raw_port.dropna(subset=[ticker_col]).copy()
            p_df = p_df[~p_df[ticker_col].astype(str).str.upper().isin(["RUR", "CNY", "USD", "EUR"])].copy()
            p_df["Тикер"] = p_df[ticker_col].astype(str).str.strip().str.upper()

            for c in raw_port.columns:
                cl = str(c).lower().strip()
                if "unnamed" in cl:
                    continue
                if any(k in cl for k in ["количеств", "кол"]):
                    p_df["Количество"] = pd.to_numeric(raw_port[c], errors="coerce").fillna(0.0)
                elif "средняя" in cl:
                    p_df["Средняя цена"] = pd.to_numeric(raw_port[c], errors="coerce").fillna(0.0)
                elif any(k in cl for k in ["цен", "price"]):
                    p_df["Цена"] = pd.to_numeric(raw_port[c], errors="coerce").fillna(0.0)
                elif any(k in cl for k in ["назван", "наименов", "эмитент"]) or cl == "name":
                    p_df["Название"] = raw_port[c].astype(str)
                elif cl in ["тип", "type"]:
                    p_df["Тип"] = raw_port[c].astype(str).str.lower()
                elif any(k in cl for k in ["валют", "curr"]):
                    p_df["Валюта"] = raw_port[c].astype(str).str.upper()
                elif any(k in cl for k in ["номинал", "facevalue", "par"]):
                    p_df["Номинал"] = pd.to_numeric(raw_port[c], errors="coerce").fillna(1000.0)
                elif any(k in cl for k in ["нкд", "accrued"]):
                    p_df["НКД"] = pd.to_numeric(raw_port[c], errors="coerce").fillna(0.0)

            fx_rates = get_moex_fx_rates()
            cur_prices_rub = []
            avg_prices_rub = []

            for _, row in p_df.iterrows():
                t = str(row.get("Тикер", "")).upper()
                typ = str(row.get("Тип", "")).lower()
                curr = str(row.get("Валюта", "RUB")).upper()
                raw_price = float(row.get("Цена", 0.0) or 0.0)
                avg_price = float(row.get("Средняя цена", 0.0) or 0.0)
                nominal = float(row.get("Номинал", 1000.0) or 1000.0)
                nkd = float(row.get("НКД", 0.0) or 0.0)

                is_bond = (
                    typ in ["bond", "облигация"]
                    or t.startswith(("RU000", "SU", "XS"))
                    or (raw_price < 250.0 and avg_price > 500.0)
                )

                if is_bond:
                    cur_p = get_bond_rub_valuation(t, raw_price, nominal, nkd, curr, fx_rates)
                    if avg_price < 250.0 and nominal >= 1000.0:
                        avg_p = get_bond_rub_valuation(t, avg_price, nominal, 0.0, curr, fx_rates)
                    else:
                        avg_p = avg_price
                else:
                    cur_p = raw_price if raw_price > 0 else avg_price
                    avg_p = avg_price if avg_price > 0 else raw_price

                cur_prices_rub.append(round(cur_p, 2))
                avg_prices_rub.append(round(avg_p, 2))

            p_df["Текущая цена"] = cur_prices_rub
            p_df["Средняя цена"] = avg_prices_rub
            p_df["Количество"] = p_df.get("Количество", 0.0).astype(float)

            p_df["Текущая стоимость"] = p_df["Количество"] * p_df["Текущая цена"]
            p_df["Вложенная сумма"] = p_df["Количество"] * p_df["Средняя цена"]
            p_df["Прибыль, ₽"] = p_df["Текущая стоимость"] - p_df["Вложенная сумма"]
            p_df["Доходность от входа, %"] = np.where(
                p_df["Вложенная сумма"] > 0,
                (p_df["Прибыль, ₽"] / p_df["Вложенная сумма"]) * 100.0,
                0.0
            )

            tot_val = p_df["Текущая стоимость"].sum()
            p_df["Вес, %"] = np.where(tot_val > 0, (p_df["Текущая стоимость"] / tot_val) * 100.0, 0.0)
            positions_df = p_df.sort_values(by="Текущая стоимость", ascending=False).reset_index(drop=True)

    # Если вкладки портфеля не было, восстанавливаем открытые позиции из сделок
    if positions_df.empty and not trades_df.empty:
        positions_df = reconstruct_positions_from_trades(trades_df)

    # 3. Дивиденды
    dividends_df = pd.DataFrame()
    if sheet_div:
        raw_div = pd.read_excel(xls, sheet_div)
        date_c = next((c for c in raw_div.columns if "дат" in str(c).lower()), None)
        if date_c:
            d_df = raw_div.dropna(subset=[date_c]).copy()
            d_df["Дата"] = pd.to_datetime(d_df[date_c])
            for col in raw_div.columns:
                cl = str(col).lower()
                if "после налога" in cl or "сумма" in cl:
                    d_df["Сумма \nпосле налога"] = pd.to_numeric(raw_div[col], errors="coerce").fillna(0.0)
            dividends_df = d_df.sort_values(by="Дата", ascending=False).reset_index(drop=True)

    # 4. Купоны
    coupons_df = pd.DataFrame()
    if sheet_coup:
        raw_coup = pd.read_excel(xls, sheet_coup)
        date_c = next((c for c in raw_coup.columns if "дат" in str(c).lower()), None)
        if date_c:
            c_df = raw_coup.dropna(subset=[date_c]).copy()
            c_df["Дата"] = pd.to_datetime(c_df[date_c])
            for col in raw_coup.columns:
                cl = str(col).lower()
                if "после налога" in cl or "сумма" in cl:
                    c_df["Сумма \nпосле налога"] = pd.to_numeric(raw_coup[col], errors="coerce").fillna(0.0)
            coupons_df = c_df.sort_values(by="Дата", ascending=False).reset_index(drop=True)

    # 5. FIFO
    fifo_df = pd.DataFrame()
    if sheet_fifo:
        raw_fifo = pd.read_excel(xls, sheet_fifo)
        buy_p = next((c for c in raw_fifo.columns if "покупк" in str(c).lower() and "цен" in str(c).lower()), None)
        sell_p = next((c for c in raw_fifo.columns if "продаж" in str(c).lower() and "цен" in str(c).lower()), None)
        if buy_p and sell_p:
            f_df = raw_fifo.dropna(subset=[buy_p, sell_p]).copy()
            buy_d = next((c for c in raw_fifo.columns if "покупк" in str(c).lower() and "дат" in str(c).lower()), "Покупка")
            sell_d = next((c for c in raw_fifo.columns if "продаж" in str(c).lower() and "дат" in str(c).lower()), "Продажа")
            
            f_df["Покупка"] = pd.to_datetime(f_df[buy_d] if buy_d in f_df.columns else datetime.now())
            f_df["Продажа"] = pd.to_datetime(f_df[sell_d] if sell_d in f_df.columns else datetime.now())
            f_df["Цена покупки"] = pd.to_numeric(f_df[buy_p], errors="coerce").fillna(0.0)
            f_df["Цена продажи"] = pd.to_numeric(f_df[sell_p], errors="coerce").fillna(0.0)
            f_df["Кол."] = pd.to_numeric(f_df.get("Кол.", f_df.get("Количество", 1.0)), errors="coerce").fillna(1.0)

            f_df["Прибыль, ₽"] = (f_df["Цена продажи"] - f_df["Цена покупки"]) * f_df["Кол."]
            f_df["Доходность, %"] = np.where(f_df["Цена покупки"] > 0, ((f_df["Цена продажи"] / f_df["Цена покупки"]) - 1.0) * 100.0, 0.0)
            f_df["Дней в сделке"] = (f_df["Продажа"] - f_df["Покупка"]).dt.days.clip(lower=1)
            f_df["Доходность годовых, %"] = (f_df["Доходность, %"] * 365.25 / f_df["Дней в сделке"]).round(2)
            fifo_df = f_df.sort_values(by="Продажа", ascending=False).reset_index(drop=True)

    # 6. Денежные потоки и XIRR
    xirr_flows: List[Tuple[datetime, float]] = []
    total_val = float(positions_df["Текущая стоимость"].sum()) if not positions_df.empty else 0.0

    if sheet_xirr:
        raw_xirr = pd.read_excel(xls, sheet_xirr).dropna(subset=["Дата", "Сумма"])
        for _, row in raw_xirr.iterrows():
            d = pd.to_datetime(row["Дата"])
            amt = float(row["Сумма"])
            xirr_flows.append((d, -amt))
    elif not trades_df.empty:
        for _, row in trades_df[trades_df["Операция"].isin(["input", "output"])].iterrows():
            d = row["Дата"]
            amt = float(row["Сумма"])
            xirr_flows.append((d, -amt))

    now_dt = datetime.now()
    if total_val > 0:
        if xirr_flows and abs(xirr_flows[-1][1] - total_val) / max(1.0, total_val) < 0.05:
            xirr_flows[-1] = (now_dt, total_val)
        else:
            xirr_flows.append((now_dt, total_val))

    xirr_value = calculate_xirr(xirr_flows)

    # 7. Сводные метрики
    total_deposits = 0.0
    total_withdrawals = 0.0
    if not trades_df.empty:
        in_mask = trades_df["Операция"] == "input"
        out_mask = trades_df["Операция"] == "output"
        total_deposits = float(trades_df.loc[in_mask, "Сумма"].sum())
        total_withdrawals = abs(float(trades_df.loc[out_mask, "Сумма"].sum()))

    net_invested = total_deposits - total_withdrawals
    if net_invested <= 0 and not positions_df.empty:
        net_invested = float(positions_df["Вложенная сумма"].sum())

    total_profit_rub = (total_val + total_withdrawals) - total_deposits
    if total_profit_rub == 0.0 and not positions_df.empty:
        total_profit_rub = float(positions_df["Прибыль, ₽"].sum())

    total_profit_pct = (total_profit_rub / net_invested * 100.0) if net_invested > 0 else 0.0

    div_total = float(dividends_df["Сумма \nпосле налога"].sum()) if not dividends_df.empty and "Сумма \nпосле налога" in dividends_df.columns else 0.0
    coup_total = float(coupons_df["Сумма \nпосле налога"].sum()) if not coupons_df.empty and "Сумма \nпосле налога" in coupons_df.columns else 0.0

    weights_dict = {}
    if not positions_df.empty:
        for _, r in positions_df.iterrows():
            t = str(r["Тикер"]).strip().upper()
            w = float(r.get("Вес, %", 0.0))
            if w > 0.01:
                weights_dict[t] = round(w, 2)

    return {
        "source": "excel_import",
        "portfolio_id": source_id,
        "identifier": identifier,
        "summary": {
            "total_value": round(total_val, 2),
            "total_deposits": round(total_deposits, 2),
            "total_withdrawals": round(total_withdrawals, 2),
            "net_invested": round(net_invested, 2),
            "total_profit_rub": round(total_profit_rub, 2),
            "total_profit_pct": round(total_profit_pct, 2),
            "xirr_pct": xirr_value,
            "total_dividends": round(div_total, 2),
            "total_coupons": round(coup_total, 2),
            "total_passive_income": round(div_total + coup_total, 2),
            "open_positions_count": len(positions_df),
            "total_trades_count": len(trades_df),
            "closed_deals_count": len(fifo_df)
        },
        "positions": positions_df,
        "trades": trades_df,
        "fifo": fifo_df,
        "dividends": dividends_df,
        "coupons": coupons_df,
        "xirr_flows": pd.DataFrame(xirr_flows, columns=["Дата", "Сумма"]),
        "weights_dict": weights_dict
    }


def parse_broker_file(file_content: Any, filename: str) -> Dict[str, Any]:
    """
    Универсальный парсер для любых файлов отчетов брокера (XLSX, XLS, CSV).
    """
    if hasattr(file_content, "read"):
        file_content = file_content.read()
    if not isinstance(file_content, (bytes, bytearray)):
        file_content = bytes(file_content)

    if len(file_content) > MAX_FILE_SIZE_BYTES:
        raise ValueError(
            f"Файл '{filename}' слишком большой ({len(file_content) / (1024 * 1024):.1f} МБ). "
            f"Максимальный допустимый размер для защиты сервера — {MAX_FILE_SIZE_BYTES // (1024 * 1024)} МБ."
        )

    fn = filename.lower()
    
    # 1. Если это XLSX или XLS
    if fn.endswith((".xlsx", ".xls")):
        try:
            return parse_izi_invest_excel(file_content, source_id="file", identifier=filename)
        except Exception as exc:
            raise ValueError(f"Ошибка чтения Excel-файла '{filename}': {exc}")

    # 2. Если это CSV
    if fn.endswith(".csv"):
        try:
            df = None
            for sep in [",", ";", "\t"]:
                try:
                    t_df = pd.read_csv(io.BytesIO(file_content), sep=sep, nrows=100000)
                    if len(t_df.columns) >= 3:
                        df = t_df
                        break
                except Exception:
                    continue

            if df is None or df.empty:
                raise ValueError("Не удалось определить разделитель CSV.")

            # Сопоставляем колонки
            col_map = {}
            for c in df.columns:
                cl = str(c).lower()
                if any(k in cl for k in ["date", "дат"]):
                    col_map["Дата"] = c
                elif any(k in cl for k in ["ticker", "тикер", "secid", "инструмент", "код"]):
                    col_map["Тикер"] = c
                elif any(k in cl for k in ["operation", "операц", "action", "вид сделки"]):
                    col_map["Операция"] = c
                elif any(k in cl for k in ["qty", "кол", "amount", "объем"]):
                    col_map["Количество"] = c
                elif any(k in cl for k in ["price", "цен"]):
                    col_map["Цена"] = c
                elif any(k in cl for k in ["sum", "сумм"]):
                    col_map["Сумма"] = c

            if "Дата" in col_map and "Тикер" in col_map:
                trades_df = pd.DataFrame({
                    "Дата": pd.to_datetime(df[col_map["Дата"]]),
                    "Тикер": df[col_map["Тикер"]].astype(str).str.strip().str.upper(),
                    "Операция": df[col_map.get("Операция", col_map["Тикер"])].astype(str).str.lower(),
                    "Количество": pd.to_numeric(df[col_map.get("Количество", 0)], errors="coerce").fillna(0.0),
                    "Цена": pd.to_numeric(df[col_map.get("Цена", 0)], errors="coerce").fillna(0.0),
                    "Сумма": pd.to_numeric(df[col_map.get("Сумма", 0)], errors="coerce").fillna(0.0),
                    "Комиссия, ₽": 0.0
                }).sort_values(by="Дата", ascending=False).reset_index(drop=True)

                positions_df = reconstruct_positions_from_trades(trades_df)
                total_val = float(positions_df["Текущая стоимость"].sum()) if not positions_df.empty else 0.0

                return {
                    "source": "csv_import",
                    "portfolio_id": filename,
                    "identifier": filename,
                    "summary": {
                        "total_value": round(total_val, 2),
                        "net_invested": round(float(positions_df["Вложенная сумма"].sum()) if not positions_df.empty else 0.0, 2),
                        "total_profit_rub": round(float(positions_df["Прибыль, ₽"].sum()) if not positions_df.empty else 0.0, 2),
                        "total_profit_pct": 0.0,
                        "xirr_pct": 0.0,
                        "total_dividends": 0.0,
                        "total_coupons": 0.0,
                        "total_passive_income": 0.0,
                        "open_positions_count": len(positions_df),
                        "total_trades_count": len(trades_df),
                        "closed_deals_count": 0
                    },
                    "positions": positions_df,
                    "trades": trades_df,
                    "fifo": pd.DataFrame(),
                    "dividends": pd.DataFrame(),
                    "coupons": pd.DataFrame(),
                    "xirr_flows": pd.DataFrame(),
                    "weights_dict": {r["Тикер"]: round(r["Вес, %"], 2) for _, r in positions_df.iterrows() if r.get("Вес, %", 0) > 0.01}
                }
        except Exception as exc:
            raise ValueError(f"Не удалось распарсить CSV файл '{filename}': {exc}")

    raise ValueError(f"Формат файла '{filename}' не поддерживается. Загрузите файл XLSX, XLS или CSV.")


# ==========================================
# 4. РАСЧЁТ ЗЕРКАЛЬНОГО БЕНЧМАРКА IMOEX
# ==========================================

def calculate_mirror_benchmark_timeline(
    trades_df: pd.DataFrame,
    current_portfolio_value: float,
    bench_symbol: str = "IMOEX"
) -> Tuple[pd.DataFrame, float]:
    """
    Симулирует «Зеркальный портфель Индекса МосБиржи»:
    Каждый раз, когда инвестор пополнял свой реальный счет (operation == 'input'),
    та же самая сумма условно инвестировалась в покупку паев IMOEX по цене на дату пополнения.
    При выводе денег (operation == 'output') часть паев продавалась.
    
    Возвращает:
    1. DataFrame с исторической траекторией капитала инвестора и зеркального индекса.
    2. Финальную доходность зеркального индекса.
    """
    if trades_df.empty or "Операция" not in trades_df.columns:
        return pd.DataFrame(), 0.0

    cash_moves = trades_df[trades_df["Операция"].isin(["input", "output"])].copy()
    if cash_moves.empty:
        return pd.DataFrame(), 0.0

    cash_moves["Дата"] = pd.to_datetime(cash_moves["Дата"]).dt.tz_localize(None)
    cash_moves = cash_moves.sort_values(by="Дата").reset_index(drop=True)

    start_date = cash_moves["Дата"].min().date()
    end_date = datetime.now().date()

    # Загружаем котировки бенчмарка IMOEX
    bench_prices: Optional[pd.Series] = None
    if Ticker is not None:
        try:
            asset = Ticker(bench_symbol)
            candles = asset.candles(date=str(start_date), till_date=str(end_date), period="D")
            if candles is not None and not candles.empty and "close" in candles.columns:
                candles["begin"] = pd.to_datetime(candles["begin"]).dt.tz_localize(None)
                bench_prices = candles.set_index("begin")["close"].astype(float).sort_index()
        except Exception:
            pass

    # Если не удалось загрузить онлайн, генерируем базовую сетку
    if bench_prices is None or bench_prices.empty:
        # Fallback: равномерная временная шкала
        date_range = pd.date_range(start_date, end_date, freq="D")
        bench_prices = pd.Series(np.linspace(2200, 2750, len(date_range)), index=date_range)

    # Симулируем накопление паев индекса при пополнениях
    bench_units = 0.0
    mirror_values = []
    
    all_dates = bench_prices.index
    # Агрегируем пополнения/выводы по дате, суммируя все движения одного дня (защита от потери повторных транзакций)
    deposit_by_date = cash_moves.groupby("Дата")["Сумма"].sum().to_dict()

    # Сопоставляем ближайшие торговые дни
    sorted_deposit_dates = sorted(deposit_by_date.keys())
    dep_idx = 0

    accumulated_invested = 0.0
    invested_series = []
    bench_series = []

    for d in all_dates:
        # Проверяем, были ли пополнения/снятия до или в этот день
        while dep_idx < len(sorted_deposit_dates) and sorted_deposit_dates[dep_idx] <= d:
            amt = float(deposit_by_date[sorted_deposit_dates[dep_idx]])
            curr_bench_px = bench_prices.asof(d)
            if curr_bench_px > 0:
                delta_units = amt / curr_bench_px
                bench_units = max(0.0, bench_units + delta_units)
                accumulated_invested += amt
            dep_idx += 1

        px = bench_prices.loc[d]
        curr_px_val = float(px.iloc[0] if isinstance(px, pd.Series) else px)
        curr_bench_val = bench_units * curr_px_val
        invested_series.append(accumulated_invested)
        bench_series.append(curr_bench_val)

    timeline_df = pd.DataFrame({
        "Дата": all_dates,
        "Вложенный капитал": invested_series,
        "Зеркальный IMOEX (₽)": bench_series
    })

    final_bench_val = bench_series[-1] if bench_series else 0.0
    bench_ret_pct = ((final_bench_val / accumulated_invested) - 1.0) * 100.0 if accumulated_invested > 0 else 0.0

    return timeline_df, round(bench_ret_pct, 2)
