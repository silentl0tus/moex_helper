"""
Клиент интеграции с MCP-сервером инвестиционного сервиса izi-invest.ru.
Обеспечивает прямое чтение состава портфелей, позиций, остатков кэша, аналитики рисков
и исторической доходности без ручной загрузки отчётов или скрапинга.
"""
from __future__ import annotations

import json
import logging
import os
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import pandas as pd
import requests
import streamlit as st

logger = logging.getLogger(__name__)

DEFAULT_MCP_URL = "https://izi-invest.ru/mcp"
DEFAULT_TOKEN = "izi_857d331baed3ff52d18941dce9c1f1d08bba2e90ca806430551d27190c7239c4"


def get_izi_config() -> Tuple[str, str]:
    """Возвращает актуальный URL и токен доступа к izi-invest MCP."""
    token = None
    url = None

    # 1. Попытка чтения из streamlit secrets
    try:
        if hasattr(st, "secrets") and "IZI_INVEST_TOKEN" in st.secrets:
            token = st.secrets["IZI_INVEST_TOKEN"]
        if hasattr(st, "secrets") and "IZI_INVEST_MCP_URL" in st.secrets:
            url = st.secrets["IZI_INVEST_MCP_URL"]
    except Exception:
        pass

    # 2. Попытка чтения из переменных окружения
    if not token:
        token = os.environ.get("IZI_INVEST_TOKEN")
    if not url:
        url = os.environ.get("IZI_INVEST_MCP_URL")

    # 3. Чтение из локального .env файла
    if not token or not url:
        env_file = Path(".env")
        if env_file.exists():
            try:
                for line in env_file.read_text(encoding="utf-8").splitlines():
                    line = line.strip()
                    if line.startswith("IZI_INVEST_TOKEN="):
                        t_val = line.split("=", 1)[1].strip().strip('"').strip("'")
                        if not token and t_val:
                            token = t_val
                    elif line.startswith("IZI_INVEST_MCP_URL="):
                        u_val = line.split("=", 1)[1].strip().strip('"').strip("'")
                        if not url and u_val:
                            url = u_val
            except Exception as e:
                logger.debug(f"Ошибка чтения .env: {e}")

    final_token = token if token else DEFAULT_TOKEN
    final_url = url if url else DEFAULT_MCP_URL
    return final_url, final_token


def _call_izi_rpc(method: str, params: Dict[str, Any], timeout: float = 10.0) -> Optional[Dict[str, Any]]:
    """Выполняет низкоуровневый JSON-RPC 2.0 запрос к izi-invest MCP."""
    url, token = get_izi_config()
    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
        "Accept": "application/json",
    }
    payload = {
        "jsonrpc": "2.0",
        "id": 1,
        "method": method,
        "params": params,
    }

    try:
        resp = requests.post(url, headers=headers, json=payload, timeout=timeout)
        if resp.status_code != 200:
            logger.warning(f"izi-invest MCP вернул статус {resp.status_code}: {resp.text[:200]}")
            return None
        data = resp.json()
        if "error" in data:
            logger.error(f"izi-invest MCP вернул RPC ошибку: {data['error']}")
            return None
        return data.get("result")
    except Exception as e:
        logger.warning(f"Ошибка подключения к izi-invest MCP ({url}): {e}")
        return None


def _call_izi_tool(tool_name: str, arguments: Dict[str, Any], timeout: float = 12.0) -> Optional[Any]:
    """Вызывает конкретный инструмент MCP и распарсивает JSON-контент ответа."""
    res = _call_izi_rpc("tools/call", {"name": tool_name, "arguments": arguments}, timeout=timeout)
    if not res:
        return None
    content = res.get("content", [])
    if content and isinstance(content, list):
        text_block = content[0].get("text", "")
        if text_block:
            try:
                return json.loads(text_block)
            except Exception:
                return text_block
    return None


@st.cache_data(ttl=300)
def get_user_portfolios() -> List[Dict[str, Any]]:
    """
    Запрашивает список всех портфелей пользователя через MCP:
    [{id, name, currency, broker_title, url, icon, ...}, ...]
    """
    res = _call_izi_tool("get_user_portfolios", {"full": False}, timeout=8.0)
    if isinstance(res, list):
        return res
    return []


@st.cache_data(ttl=180)
def fetch_portfolio_raw(
    portfolio_id: int,
    blocks: Optional[List[str]] = None,
    points: int = 60,
) -> Optional[Dict[str, Any]]:
    """
    Запрашивает сырые данные портфеля по блокам: summary, positions, structure, chart.
    """
    if blocks is None:
        blocks = ["summary", "positions", "structure", "chart"]
    res = _call_izi_tool(
        "get_portfolio",
        {"portfolio_id": int(portfolio_id), "blocks": blocks, "points": points},
        timeout=12.0,
    )
    if isinstance(res, dict):
        return res
    return None


@st.cache_data(ttl=300)
def fetch_portfolio_analysis(portfolio_id: int) -> Optional[Dict[str, Any]]:
    """
    Запрашивает глубокую аналитику портфеля от izi-invest:
    риски (HHI, топ-5), бенчмарки (XIRR, AAR vs IMOEX/ЦБ), диагностику.
    """
    res = _call_izi_tool("get_analysis", {"portfolio_id": int(portfolio_id)}, timeout=10.0)
    if isinstance(res, dict):
        return res
    return None


def get_portfolio_model(portfolio_id: int) -> Dict[str, Any]:
    """
    Универсальный высокоуровневый агрегатор:
    Преобразует ответ izi-invest MCP в унифицированную модель данных для MOEX Helper:
    - positions_df: DataFrame открытых позиций с лотами, ценами, долями и PnL
    - summary: словарь итоговых финансовых метрик (капитал, вложено, кэш, доходность)
    - structure: отраслевое и брокерское распределение (Альфа vs ВТБ)
    - chart_df: историческая траектория капитала против бенчмарка MCFTRR
    - analysis: диагностика рисков и концентрации
    """
    raw = fetch_portfolio_raw(portfolio_id)
    if not raw:
        return {}

    summary = raw.get("summary", {})
    pos_block = raw.get("positions", {})
    structure = raw.get("structure", {})
    chart_block = raw.get("chart", {})

    # 1. Извлечение позиций
    items = pos_block.get("items", []) if isinstance(pos_block, dict) else []
    pos_rows = []
    my_portfolio_dict = {}
    my_reserves_dict = {}
    my_blocked_dict = {}

    for it in items:
        uid = it.get("uid", "")
        ticker = uid.split(":")[0] if ":" in uid else uid
        ticker = ticker.upper().strip()
        cnt = float(it.get("cnt", 0))
        price = float(it.get("price_pc", 0.0))
        summa = float(it.get("summa", 0.0))
        avg_price = float(it.get("average_price_pc", 0.0))
        invested = avg_price * cnt if avg_price > 0 else summa
        pnl_rub = float(it.get("yield", 0.0))
        pnl_pct = float(it.get("dpercent", 0.0))
        share = float(it.get("proportion", 0.0))
        asset_type = str(it.get("type", "share")).lower()

        # Классификация активов: акции vs облигации vs заблокированные фонды
        is_blocked = ticker.startswith("FX") or ticker in ["RUSE", "RSHE", "FIXR"]
        is_bond = asset_type == "bond" or ticker.startswith("RU000") or ticker.startswith("SU26")

        if is_blocked:
            my_blocked_dict[ticker] = {
                "count": cnt,
                "invested": invested,
                "avg_price": avg_price,
                "val": summa,
                "name": it.get("name", ticker)
            }
        elif is_bond:
            my_reserves_dict[ticker] = {
                "count": cnt,
                "invested": invested,
                "avg_price": avg_price,
                "val": summa,
                "name": it.get("name", ticker)
            }
        else:
            my_portfolio_dict[ticker] = {
                "count": cnt,
                "invested": invested,
                "avg_price": avg_price,
                "val": summa,
                "name": it.get("name", ticker)
            }

        pos_rows.append({
            "ticker": ticker,
            "name": it.get("name", ticker),
            "lots": cnt,
            "cnt": cnt,
            "count": cnt,
            "price": price,
            "invested": invested,
            "total_cost": invested,
            "current_val": summa,
            "val": summa,
            "avg_price": avg_price,
            "pnl_rub": pnl_rub,
            "pnl_pct": pnl_pct,
            "share_pct": share,
            "weight": share,
            "type": asset_type,
            "asset_type": asset_type,
            "icon": it.get("icon", ""),
            "url": it.get("url", ""),
            # Русскоязычные алиасы для страницы детального аудита:
            "Тикер": ticker,
            "Название": it.get("name", ticker),
            "Тип": "Облигация" if is_bond else ("Фонд ETF" if is_blocked else "Акция"),
            "Количество": cnt,
            "Средняя цена": avg_price,
            "Текущая цена": price,
            "Вложенная сумма": invested,
            "Текущая стоимость": summa,
            "Прибыль, ₽": pnl_rub,
            "Доходность от входа, %": pnl_pct,
            "Доля в портфеле, %": share,
            "Вес, %": share,
        })

    positions_df = pd.DataFrame(pos_rows)

    # 2. Обработка кэша и остатков
    cash_block = summary.get("cash", {})
    cash_rur = float(cash_block.get("RUR", 0.0)) if isinstance(cash_block, dict) else 0.0
    cash_cny = float(cash_block.get("CNY", 0.0)) if isinstance(cash_block, dict) else 0.0
    cny_rate = 13.5  # Приблизительный курс CNY/RUB
    total_cash_rub = cash_rur + (cash_cny * cny_rate)

    balance_parts = summary.get("balance_parts", {})
    shares_val = float(balance_parts.get("shares", 0.0)) if isinstance(balance_parts, dict) else 0.0
    bonds_val = float(balance_parts.get("bonds", 0.0)) if isinstance(balance_parts, dict) else 0.0
    total_cash_val = float(balance_parts.get("cash", cash_rur)) if isinstance(balance_parts, dict) else cash_rur

    total_val = float(summary.get("balance", 0.0))
    money_invested = summary.get("money", {}).get("invested", 0.0) if isinstance(summary.get("money"), dict) else 0.0
    total_inv = float(money_invested) if money_invested else total_val

    pnl_rub = float(summary.get("yield", 0.0))
    pnl_pct = float(summary.get("yield_perc", 0.0))

    # Резервы (облигации + кэш)
    reserves_market_val = bonds_val + total_cash_rub

    # Если загружается сводный портфель «Ликвидная часть» (47933), автоматически обогащаем
    # заблокированными фондами FinEx из суб-портфеля LOCK (43551), чтобы инвестор видел полный капитал
    if int(portfolio_id) == 47933 and not my_blocked_dict:
        try:
            lock_raw = fetch_portfolio_raw(43551)
            if lock_raw and isinstance(lock_raw.get("positions"), dict):
                lock_items = lock_raw["positions"].get("items", [])
                for it in lock_items:
                    uid = it.get("uid", "")
                    tk = uid.split(":")[0] if ":" in uid else uid
                    tk = tk.upper().strip()
                    c_cnt = float(it.get("cnt", 0))
                    c_sum = float(it.get("summa", 0.0))
                    c_avg = float(it.get("average_price_pc", 0.0))
                    c_inv = c_avg * c_cnt if c_avg > 0 else c_sum
                    my_blocked_dict[tk] = {
                        "count": c_cnt,
                        "invested": c_inv,
                        "avg_price": c_avg,
                        "val": c_sum,
                        "name": it.get("name", tk)
                    }
        except Exception:
            pass

    blocked_total_val = sum(v["val"] for v in my_blocked_dict.values())

    # 3. Обработка исторического графика (Chart)
    chart_items = chart_block.get("items", []) if isinstance(chart_block, dict) else []
    chart_rows = []
    for pt in chart_items:
        d_str = pt.get("date")
        if d_str:
            chart_rows.append({
                "date": pd.to_datetime(d_str),
                "Дата": pd.to_datetime(d_str),
                "balance": float(pt.get("b", 0.0)),
                "invested": float(pt.get("io", 0.0)),
                "yield": float(pt.get("y", 0.0)),
                "mcftrr_curve": float(pt.get("m", 0.0)),
                "imoex_curve": float(pt.get("p", 0.0)),
                # Алиасы для отрисовки графиков:
                "Портфель инвестора": float(pt.get("b", 0.0)),
                "Вложенный капитал": float(pt.get("io", 0.0)),
                "MCFTRR (Полная доходность «нетто»)": float(pt.get("m", 0.0)),
                "Индекс МосБиржи (IMOEX)": float(pt.get("p", 0.0)),
            })
    chart_df = pd.DataFrame(chart_rows)

    # 4. Аналитика рисков
    analysis = fetch_portfolio_analysis(portfolio_id) or {}

    # Название портфеля
    p_name = analysis.get("name")
    if not p_name:
        for p_info in get_user_portfolios():
            if p_info.get("id") == portfolio_id:
                p_name = p_info.get("name", "")
                break
    if not p_name:
        p_name = f"Портфель #{portfolio_id}"

    return {
        "portfolio_id": portfolio_id,
        "portfolio_name": p_name,
        "positions_df": positions_df,
        "my_portfolio_dict": my_portfolio_dict,
        "my_reserves_dict": my_reserves_dict,
        "my_blocked_dict": my_blocked_dict,
        "reserves_market_value": reserves_market_val,
        "blocked_total": blocked_total_val,
        "cash_rub": total_cash_rub,
        "summary": {
            "total_val": total_val,
            "total_inv": total_inv,
            "pnl_rub": pnl_rub,
            "pnl_pct": pnl_pct,
            "cash_rub": cash_rur,
            "cash_cny": cash_cny,
            "total_cash": total_cash_val,
            "total_cash_rub": total_cash_rub,
            "shares_val": shares_val,
            "bonds_val": bonds_val,
            "xirr": float(summary.get("xirr", 0.0)),
            "aar": float(summary.get("aar", 0.0)),
            "start_date": summary.get("start_date", ""),
            "day_pnl_rub": summary.get("day", {}).get("yield", 0.0) if isinstance(summary.get("day"), dict) else 0.0,
            "day_pnl_pct": summary.get("day", {}).get("balance_perc", 0.0) if isinstance(summary.get("day"), dict) else 0.0,
            "divs_received": summary.get("income", {}).get("dividends", 0.0) if isinstance(summary.get("income"), dict) else 0.0,
            "coupons_received": summary.get("income", {}).get("coupons", 0.0) if isinstance(summary.get("income"), dict) else 0.0,
            "tax_paid": summary.get("income", {}).get("tax", 0.0) if isinstance(summary.get("income"), dict) else 0.0,
            "commission_paid": summary.get("income", {}).get("commission", 0.0) if isinstance(summary.get("income"), dict) else 0.0,
        },
        "structure": structure,
        "chart_df": chart_df,
        "analysis": analysis,
        "is_mcp": True,
    }
