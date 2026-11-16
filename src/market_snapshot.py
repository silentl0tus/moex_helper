"""Живые рыночные данные для страниц, у которых нет собственного загрузчика (Мастер подбора и др.).

Источники и порядок резерва:
- макро (ключевая ставка, USD/RUB): izi-invest MCP `get_market_context` -> cbr.ru -> значение по умолчанию;
- цены акций: один запрос MOEX ISS по борду TQBR (LAST, при отсутствии сделок — PREVPRICE);
- рейтинг долга по облигациям и эмитенты с валютным долгом: Magellan / MOEX (с их собственными резервами).
Любой сбой возвращает пустой результат — страница обязана это показать, а не подставлять выдуманные числа.
"""
from __future__ import annotations

import os
import re
from typing import Any, Dict

import requests
import streamlit as st

_LOADED_FILE_MTIME = os.path.getmtime(__file__)

DEFAULT_KEY_RATE = 16.0
MOEX_TQBR_URL = "https://iss.moex.com/iss/engines/stock/markets/shares/boards/TQBR/securities.json"


@st.cache_data(ttl=600, show_spinner=False)
def fetch_macro_snapshot() -> Dict[str, Any]:
    """Возвращает {key_rate, usd_rate, source, is_live}. is_live=False — ставка взята по умолчанию, а не из источника."""
    key_rate = None
    usd_rate = None
    source = ""

    try:
        from src.izi_mcp_client import _call_izi_tool

        ctx = _call_izi_tool("get_market_context", {}, timeout=(4.0, 10.0))
        if isinstance(ctx, dict):
            if ctx.get("cbr_rate") is not None:
                key_rate = float(ctx["cbr_rate"])
            fx = ctx.get("fx") if isinstance(ctx.get("fx"), dict) else {}
            if fx.get("USD") is not None:
                usd_rate = float(fx["USD"])
            if key_rate is not None:
                source = "izi-invest MCP"
    except Exception:
        pass

    if key_rate is None:
        try:
            resp = requests.get(
                "https://cbr.ru/hd_base/KeyRate/", headers={"User-Agent": "Mozilla/5.0"}, timeout=3
            )
            match = re.search(r"<td>(\d{2}[,.]\d{2})</td>", resp.text)
            if match:
                key_rate = float(match.group(1).replace(",", "."))
                source = "cbr.ru"
        except Exception:
            pass

    is_live = key_rate is not None
    return {
        "key_rate": key_rate if is_live else DEFAULT_KEY_RATE,
        "usd_rate": usd_rate,
        "source": source or "значение по умолчанию",
        "is_live": is_live,
    }


@st.cache_data(ttl=300, show_spinner=False)
def fetch_moex_last_prices() -> Dict[str, float]:
    """Цены всех акций TQBR одним запросом: {ticker: price}. Пустой словарь, если MOEX ISS недоступен."""
    try:
        resp = requests.get(
            MOEX_TQBR_URL,
            params={
                "iss.meta": "off",
                "iss.only": "securities,marketdata",
                "securities.columns": "SECID,PREVPRICE",
                "marketdata.columns": "SECID,LAST",
            },
            timeout=(4.0, 8.0),
        )
        resp.raise_for_status()
        data = resp.json()
    except Exception:
        return {}

    prices: Dict[str, float] = {}
    for secid, prev in data.get("securities", {}).get("data", []):
        if secid and prev:
            prices[secid] = float(prev)
    for secid, last in data.get("marketdata", {}).get("data", []):
        if secid and last:
            prices[secid] = float(last)
    return prices


@st.cache_data(ttl=1800, show_spinner=False)
def fetch_bond_stress() -> Dict[str, Dict[str, Any]]:
    """Долговой радар по облигациям эмитентов (YTM, уровень риска). Пустой словарь при сбое."""
    try:
        from src.magellan_gateway import MagellanGateway

        return MagellanGateway().get_bonds_stress_radar()
    except Exception:
        return {}


@st.cache_data(ttl=1800, show_spinner=False)
def fetch_fx_debt_issuers() -> Dict[str, list]:
    """Эмитенты с валютными облигациями (TQOD/TQOY). Пустой словарь при сбое."""
    try:
        from src.magellan_gateway import MagellanGateway

        return MagellanGateway().get_fx_debt_issuers()
    except Exception:
        return {}
