"""Обогащение таблицы мультипликаторов данными Data Foundry MCP и MOEX ISS.

Модуль намеренно НЕ зависит от `streamlit`, чтобы одинаково работать:
- в автономном парсере `fetch_fundamentals.py` (включая GitHub Actions);
- в расчётном ядре `src/black_line.py` (единые функции LTM, последней точки баланса и темпа выручки).
"""
from __future__ import annotations

import asyncio
from concurrent.futures import ThreadPoolExecutor
import datetime
from decimal import Decimal
import logging
import os
import time
from typing import Any, Callable, Dict, Iterable, Optional, Tuple

import pandas as pd
import requests

_LOADED_FILE_MTIME = os.path.getmtime(__file__)

logger = logging.getLogger(__name__)

FOUNDRY_MCP_URL = "https://mcp.vrednyj-investor.ru/mcp"
MOEX_TQBR_URL = "https://iss.moex.com/iss/engines/stock/markets/shares/boards/TQBR/securities.json"

# Тикеры на MOEX, которые в Data Foundry MCP числятся под другим тикером компании
MCP_TICKER_ALIASES: Dict[str, str] = {
    "CNRU": "CIAN",
    "SNGS": "SNGSP",
}

BANK_METRICS: Tuple[str, ...] = (
    "fin.total_equity",
    "fin.equity_attributable_to_owners",
    "fin.net_income",
)

REAL_SECTOR_METRICS: Tuple[str, ...] = (
    "fin.total_equity",
    "fin.equity_attributable_to_owners",
    "fin.net_income",
    "fin.revenue",
    "fin.ebitda",
    "fin.operating_profit",
    "fin.interest_bearing_debt",
    "fin.cash_and_equivalents",
    "fin.operating_cash_flow",
    "fin.capex",
)


def period_sort_key(k: str) -> Tuple[int, int, str]:
    """Сортирует финансовые периоды (2024-FY, ASOF:2024-12-31, 2025-H1, 2026-9M) хронологически."""
    clean_k = str(k).replace("ASOF:", "")
    parts = clean_k.split("-")
    year = int(parts[0]) if parts and parts[0].isdigit() else 0
    sub = parts[1] if len(parts) > 1 else ""
    order = {"Q1": 1, "03": 1, "H1": 2, "06": 2, "9M": 3, "09": 3, "Q3": 3, "Q4": 4, "FY": 4, "12": 4}
    sub_rank = 0
    for prefix, rank in order.items():
        if sub.startswith(prefix):
            sub_rank = rank
            break
    return (year, sub_rank, str(k))


def _to_float(val: Any) -> Optional[float]:
    if val is None:
        return None
    try:
        return float(Decimal(str(val)))
    except Exception:
        return None


def _run_async(coro):
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        loop = None
    if loop and loop.is_running():
        with ThreadPoolExecutor(max_workers=1) as pool:
            return pool.submit(asyncio.run, coro).result()
    return asyncio.run(coro)


def _year_of_label(label: Optional[str]) -> Optional[int]:
    if not label:
        return None
    s = str(label).replace("LTM 4Q до ", "").replace("LTM ", "").replace("ASOF:", "")
    head = s.split("-", 1)[0]
    return int(head) if head.isdigit() else None


def compute_ltm_flow(series: Dict[str, float]) -> Tuple[Optional[float], Optional[str]]:
    """Вычисляет LTM для потоковой метрики (прибыль, выручка, OCF, CAPEX).

    Приоритет:
    1. Последний закрытый год `YYYY-FY`, если по новому году ещё нет отчётности.
    2. Свежая неполная отчётность нового года (9M/H1/Q1) + прошлый год − сопоставимый период прошлого года.
    3. Сумма 4 последовательных дискретных кварталов (если годового/накопленного ряда нет).
    Не проваливается глубже чем на 1 год от максимального года в ряду (защита от подмены LTM-2026 данными 2021 года).
    """
    if not series:
        return None, None

    years = sorted(
        {int(k.split("-")[0]) for k in series if "-" in k and not k.startswith("ASOF:") and k.split("-")[0].isdigit()},
        reverse=True,
    )
    if not years:
        return None, None
    min_fresh_year = years[0] - 1

    for y in years:
        if y < min_fresh_year:
            break
        fy_key = f"{y}-FY"
        if fy_key in series:
            return series[fy_key], fy_key
        for suffix in ("9M", "H1", "Q1"):
            cur_key = f"{y}-{suffix}"
            prev_fy = f"{y - 1}-FY"
            prev_part = f"{y - 1}-{suffix}"
            if cur_key in series and prev_fy in series and prev_part in series:
                ltm = series[prev_fy] - series[prev_part] + series[cur_key]
                return ltm, f"LTM {cur_key}"

    # Вариант по 4 дискретным кварталам (самый свежий доступный конец в пределах окна свежести)
    q_order = [("Q1", 1), ("Q2", 2), ("Q3", 3), ("Q4", 4)]
    q_points = []
    for k in series:
        if k.startswith("ASOF:") or "-" not in k:
            continue
        yr_s, sub = k.split("-", 1)
        if yr_s.isdigit():
            rank = dict(q_order).get(sub)
            if rank:
                q_points.append((int(yr_s), rank, k))
    q_points.sort()
    if len(q_points) >= 4:
        tail4 = q_points[-4:]
        steps = [(yr * 4 + rk) for yr, rk, _ in tail4]
        if tail4[-1][0] >= min_fresh_year and steps == [steps[0], steps[0] + 1, steps[0] + 2, steps[0] + 3] and f"{tail4[-1][0]}-FY" not in series:
            return sum(series[k] for _, _, k in tail4), f"LTM 4Q до {tail4[-1][2]}"

    return None, None


def pick_latest_instant(series: Dict[str, float]) -> Tuple[Optional[float], Optional[str]]:
    """Возвращает последнее по дате значение балансовой статьи (`ASOF:YYYY-MM-DD`)."""
    if not series:
        return None, None
    asof_keys = [k for k in series if k.startswith("ASOF:")]
    pool = asof_keys if asof_keys else list(series.keys())
    best_key = max(pool, key=period_sort_key)
    return series[best_key], best_key


def compute_yoy_revenue_growth(series: Dict[str, float]) -> Optional[float]:
    """Темп прироста выручки г/г по сопоставимым последним периодам (или LTM vs прошлый FY)."""
    if not series:
        return None

    # 1. Сравнение последнего LTM против последнего закрытого года (если LTM свежее закрытого FY)
    ltm_val, ltm_lbl = compute_ltm_flow(series)
    fy_keys = sorted([k for k in series if k.endswith("-FY") and not k.startswith("ASOF:")], key=period_sort_key)
    if ltm_val is not None and ltm_lbl and ltm_lbl.startswith("LTM "):
        ltm_part = ltm_lbl.replace("LTM ", "")
        cur_y = int(ltm_part.split("-")[0])
        suffix = ltm_part.split("-")[1]
        cur_p = f"{cur_y}-{suffix}"
        prev_p = f"{cur_y - 1}-{suffix}"
        if cur_p in series and prev_p in series and series[prev_p] > 0:
            return round(((series[cur_p] - series[prev_p]) / abs(series[prev_p])) * 100.0, 2)

    if len(fy_keys) >= 2:
        prev_val = series[fy_keys[-2]]
        last_val = series[fy_keys[-1]]
        if prev_val > 0:
            return round(((last_val - prev_val) / abs(prev_val)) * 100.0, 2)
    return None


def fetch_moex_capitalization_map(timeout: float = 8.0) -> Dict[str, Dict[str, float]]:
    """Загружает цены и капитализацию TQBR; `total_cap` суммирует обыкновенные и привилегированные акции."""
    try:
        resp = requests.get(
            MOEX_TQBR_URL,
            params={
                "iss.meta": "off",
                "iss.only": "securities,marketdata",
                "securities.columns": "SECID,ISSUESIZE,PREVPRICE",
                "marketdata.columns": "SECID,LAST,ISSUECAPITALIZATION",
            },
            timeout=timeout,
        )
        resp.raise_for_status()
        data = resp.json()
    except Exception as exc:
        logger.warning(f"MOEX capitalization fetch failed: {exc}")
        return {}

    sec_map: Dict[str, Tuple[Optional[float], Optional[float]]] = {}
    for secid, isize, prev in data.get("securities", {}).get("data", []):
        if secid:
            sec_map[secid] = (
                float(isize) if isize else None,
                float(prev) if prev else None,
            )

    md_map: Dict[str, Tuple[Optional[float], Optional[float]]] = {}
    for secid, last, mcap in data.get("marketdata", {}).get("data", []):
        if secid:
            md_map[secid] = (
                float(last) if last else None,
                float(mcap) if mcap else None,
            )

    def _cap_and_price(secid: str) -> Tuple[Optional[float], Optional[float]]:
        isize, prev = sec_map.get(secid, (None, None))
        last, mcap = md_map.get(secid, (None, None))
        price = last or prev
        if not mcap and price and isize:
            mcap = price * isize
        return price, mcap

    out: Dict[str, Dict[str, float]] = {}
    for secid in sec_map:
        price, common_cap = _cap_and_price(secid)
        total_cap = common_cap
        if not secid.endswith("P"):
            _, pref_cap = _cap_and_price(secid + "P")
            if total_cap and pref_cap:
                total_cap = total_cap + pref_cap
        out[secid] = {
            "price": price,
            "common_cap": common_cap,
            "total_cap": total_cap,
        }
    return out


def _pick_preferred_variant(choices: list[dict[str, Any]]) -> Optional[str]:
    """Предпочитает консолидированный срез `geography=group` / `business_segment=all`."""
    for ch in choices:
        dims = ch.get("dimensions") or {}
        if dims.get("geography") == "group" or dims.get("business_segment") == "all":
            return ch.get("variant") or ch.get("selector")
    for ch in choices:
        var = ch.get("variant") or ch.get("selector")
        if var:
            return var
    return None


def _parse_mcp_payload(res) -> Dict[str, Any]:
    if hasattr(res, "structured_content") and isinstance(res.structured_content, dict):
        return res.structured_content
    import json
    for item in getattr(res, "content", []) or []:
        if hasattr(item, "text"):
            try:
                return json.loads(item.text)
            except Exception:
                return {}
    return {}


async def _call_tool_with_retry(session, tool_name: str, args: Dict[str, Any], max_retries: int = 2):
    """Вызов MCP-инструмента с повторной попыткой при 429 / кратковременном сетевом сбое."""
    for attempt in range(max_retries + 1):
        try:
            return await session.call_tool(tool_name, args)
        except Exception as exc:
            if attempt >= max_retries:
                raise
            wait_s = 1.2 * (attempt + 1)
            logger.debug(f"MCP retry ({attempt + 1}/{max_retries}) in {wait_s:.1f}s after: {exc}")
            await asyncio.sleep(wait_s)


async def _fetch_mcp_async(
    ticker_metrics: Dict[str, Tuple[str, ...]],
    pause_sec: float = 0.22,
    accounting_basis: str = "IFRS",
) -> Dict[str, Dict[str, Dict[str, float]]]:
    """Последовательный вежливый опрос Data Foundry MCP в одной сессии без burst-нагрузки."""
    from mcp import ClientSession
    from mcp.client.streamable_http import streamable_http_client

    allowed_bases = (accounting_basis, "APM", None) if accounting_basis == "IFRS" else (accounting_basis, None)
    results: Dict[str, Dict[str, Dict[str, float]]] = {}

    async with streamable_http_client(FOUNDRY_MCP_URL) as (rd, wr):
        async with ClientSession(rd, wr) as session:
            await session.initialize()
            for orig_tk, metrics in ticker_metrics.items():
                mcp_tk = MCP_TICKER_ALIASES.get(orig_tk, orig_tk)
                tk_bucket: Dict[str, Dict[str, float]] = {}
                for metric in metrics:
                    args: Dict[str, Any] = {
                        "companies": [mcp_tk],
                        "metrics": [metric],
                        "revisions": "current",
                        "limit": 100,
                    }
                    try:
                        res = await _call_tool_with_retry(session, "get_series", args)
                        d = _parse_mcp_payload(res)
                        if d.get("status") == "ambiguous" and d.get("choices"):
                            items = []
                            pref_var = _pick_preferred_variant(d["choices"])
                            ordered_vars = [pref_var] + [
                                c.get("variant") or c.get("selector")
                                for c in d["choices"][:2]
                                if (c.get("variant") or c.get("selector")) != pref_var
                            ]
                            for var in ordered_vars:
                                if not var:
                                    continue
                                if pause_sec > 0:
                                    await asyncio.sleep(pause_sec)
                                args_v = dict(args, variants=[var])
                                res_v = await _call_tool_with_retry(session, "get_series", args_v)
                                d_v = _parse_mcp_payload(res_v)
                                items.extend(d_v.get("items", []))
                        else:
                            items = d.get("items", [])

                        per_map: Dict[str, float] = {}
                        for it in items:
                            basis = it.get("accounting_basis")
                            if basis not in allowed_bases:
                                continue
                            pk = (it.get("period") or {}).get("key")
                            fval = _to_float(it.get("value"))
                            if pk and fval is not None:
                                if pk not in per_map or basis == accounting_basis:
                                    per_map[pk] = fval
                        if per_map:
                            tk_bucket[metric] = per_map
                    except Exception as exc:
                        logger.debug(f"MCP error for {orig_tk} ({mcp_tk}) {metric}: {exc}")
                    if pause_sec > 0:
                        await asyncio.sleep(pause_sec)
                results[orig_tk] = tk_bucket
    return results


def fetch_mcp_series_for_tickers(
    ticker_metrics: Dict[str, Tuple[str, ...]],
    pause_sec: float = 0.22,
    accounting_basis: str = "IFRS",
) -> Dict[str, Dict[str, Dict[str, float]]]:
    """Безопасная обёртка над MCP-опросом: при недоступности `mcp` или сети возвращает `{}`."""
    if not ticker_metrics:
        return {}
    try:
        return _run_async(_fetch_mcp_async(ticker_metrics, pause_sec=pause_sec, accounting_basis=accounting_basis))
    except Exception as exc:
        logger.warning(f"Data Foundry MCP batch unavailable: {exc}")
        return {}


def _pick_fresher_equity(
    raw_series: Dict[str, Dict[str, float]],
    prefer_attributable_equity: bool = True,
) -> Tuple[Optional[float], Optional[str]]:
    """Выбирает наиболее свежий баланс капитала (предпочитает attributable лишь если дата не старее total_equity)."""
    tot_val, tot_pk = pick_latest_instant(raw_series.get("fin.total_equity", {}))
    attr_val, attr_pk = pick_latest_instant(raw_series.get("fin.equity_attributable_to_owners", {}))
    if not prefer_attributable_equity or attr_val is None:
        return tot_val, tot_pk
    if tot_val is None or period_sort_key(attr_pk) >= period_sort_key(tot_pk):
        return attr_val, attr_pk
    return tot_val, tot_pk


def derive_multiples_from_mcp(
    raw_series: Dict[str, Dict[str, float]],
    total_cap: Optional[float],
    prefer_attributable_equity: bool = True,
    reference_year: Optional[int] = None,
) -> Dict[str, Any]:
    """Вычисляет чистые LTM-мультипликаторы из сырых рядов МСФО/РСФО и рыночной капитализации."""
    eq, eq_period = _pick_fresher_equity(raw_series, prefer_attributable_equity=prefer_attributable_equity)
    ni, ni_period = compute_ltm_flow(raw_series.get("fin.net_income", {}))
    rev, rev_period = compute_ltm_flow(raw_series.get("fin.revenue", {}))
    rev_growth = compute_yoy_revenue_growth(raw_series.get("fin.revenue", {}))

    eq_year = _year_of_label(eq_period)
    ni_year = _year_of_label(ni_period)
    if reference_year is not None:
        if eq_year is not None and eq_year < reference_year - 2:
            eq, eq_period, eq_year = None, None, None
        if ni_year is not None and ni_year < reference_year - 2:
            ni, ni_period, ni_year = None, None, None
    if eq_year is not None and ni_year is not None and abs(eq_year - ni_year) > 1:
        ni, ni_period = None, None

    ebitda_series = raw_series.get("fin.ebitda") or raw_series.get("fin.operating_profit") or {}
    ebitda, _ = compute_ltm_flow(ebitda_series)
    debt, _ = pick_latest_instant(raw_series.get("fin.interest_bearing_debt", {}))
    cash, _ = pick_latest_instant(raw_series.get("fin.cash_and_equivalents", {}))

    ocf, ocf_p = compute_ltm_flow(raw_series.get("fin.operating_cash_flow", {}))
    capex, capex_p = compute_ltm_flow(raw_series.get("fin.capex", {}))

    # Отсечка явных ошибок размерности в исходной отчётности MCP (напр. млн вместо тыс. для 2025-FY)
    ni_scale_ok = ni is not None and not (
        (total_cap and total_cap > 0 and abs(ni) > total_cap * 10.0)
        or (eq and eq > 0 and abs(ni / eq) > 3.0)
    )
    if not ni_scale_ok:
        ni = None

    pb = round(total_cap / eq, 2) if (total_cap and eq and eq > 0) else None
    pe = round(total_cap / ni, 2) if (total_cap and ni and ni != 0) else None
    roe = round((ni / eq) * 100.0, 1) if (ni is not None and eq and eq > 0) else None

    net_debt = (debt - cash) if (debt is not None and cash is not None) else None
    debt_ebitda = None
    if net_debt is not None:
        if ebitda and ebitda > 0:
            debt_ebitda = round(net_debt / ebitda, 2)
        elif debt <= cash:
            debt_ebitda = -0.5

    fcf_yield = None
    if ocf is not None and capex is not None and total_cap and total_cap > 0 and ocf_p == capex_p:
        fcf = ocf - abs(capex)
        fcf_yield = round((fcf / total_cap) * 100.0, 2)

    return {
        "P_BV": pb,
        "P_E": pe,
        "ROE_%": roe,
        "Rev_Growth_%": rev_growth,
        "Debt_EBITDA": debt_ebitda,
        "FCF_Yield_%": fcf_yield,
        "equity": eq,
        "net_income": ni,
        "revenue": rev,
        "ebitda": ebitda,
        "cash": cash,
        "debt": debt,
        "net_debt": net_debt,
        "eq_period": eq_period,
        "ni_period": ni_period or rev_period or eq_period or "LTM",
    }


def _has_gap(row: pd.Series, cols: Iterable[str]) -> bool:
    return any(pd.isna(row.get(c)) for c in cols)


def enrich_fundamentals_with_mcp(
    df: pd.DataFrame,
    bank_tickers: Iterable[str],
    cap_map: Optional[Dict[str, Dict[str, float]]] = None,
    mcp_by_ticker: Optional[Dict[str, Dict[str, Dict[str, float]]]] = None,
    pause_sec: float = 0.22,
    reference_year: Optional[int] = None,
) -> pd.DataFrame:
    """Точечно дополняет DataFrame из smart-lab данными Data Foundry MCP + MOEX ISS.

    Правила согласованности:
    - Для банков: если MCP даёт оба компонента (`equity > 0` и `LTM net_income`), `P_BV`, `P_E` и `ROE_%`
      обновляются **единой согласованной тройкой** (чтобы не смешивать старый ROE с новым капиталом).
      Если в MCP есть только баланс или данные MCP недоступны, `P_BV` достраивается как `P_E * ROE_% / 100`
      (а при отсутствии и этого — `total_cap / equity`). `Debt_EBITDA` у банков не ниже `1.0` при `NaN`.
    - Для небанковских бумаг: MCP заполняет только пропущенные (`NaN`) ячейки `P_BV`, `P_E`, `ROE_%`,
      `Rev_Growth_%`, `Debt_EBITDA`, `FCF_Yield_%`, не ломая рабочий парсинг smart-lab.
    """
    if df.empty:
        return df

    out = df.copy()
    banks = {t.upper() for t in bank_tickers}
    gap_cols = ("ROE_%", "P_E", "P_BV", "Rev_Growth_%", "Debt_EBITDA")
    ref_year = reference_year if reference_year is not None else datetime.date.today().year

    if cap_map is None:
        cap_map = fetch_moex_capitalization_map()

    if mcp_by_ticker is None:
        query_plan: Dict[str, Tuple[str, ...]] = {}
        for _, row in out.iterrows():
            tk = str(row["ticker"]).upper()
            if tk in banks:
                need_rev = "Rev_Growth_%" in out.columns and pd.isna(row.get("Rev_Growth_%"))
                query_plan[tk] = BANK_METRICS + (("fin.revenue",) if need_rev else ())
            elif _has_gap(row, gap_cols):
                query_plan[tk] = REAL_SECTOR_METRICS
        mcp_by_ticker = fetch_mcp_series_for_tickers(query_plan, pause_sec=pause_sec)

    for idx, row in out.iterrows():
        tk = str(row["ticker"]).upper()
        cap_info = cap_map.get(tk) or {}
        total_cap = cap_info.get("total_cap") or cap_info.get("common_cap")
        derived = derive_multiples_from_mcp(mcp_by_ticker.get(tk, {}), total_cap, reference_year=ref_year)

        if tk in banks:
            if pd.isna(out.at[idx, "Debt_EBITDA"]) if "Debt_EBITDA" in out.columns else True:
                out.at[idx, "Debt_EBITDA"] = 1.0

            has_consistent_triple = (
                derived["P_BV"] is not None
                and derived["P_E"] is not None
                and derived["ROE_%"] is not None
                and derived["net_income"] is not None
                and derived["net_income"] > 0
            )
            if has_consistent_triple:
                out.at[idx, "P_BV"] = derived["P_BV"]
                out.at[idx, "P_E"] = derived["P_E"]
                out.at[idx, "ROE_%"] = derived["ROE_%"]
            else:
                # Если LTM в MCP неполный (например, VTBR с госпрефами) — согласованный расчёт P/BV через P/E * ROE
                pe_cur = out.at[idx, "P_E"] if "P_E" in out.columns else None
                roe_cur = out.at[idx, "ROE_%"] if "ROE_%" in out.columns else None
                if pd.isna(out.at[idx, "P_BV"]) if "P_BV" in out.columns else True:
                    if pd.notna(pe_cur) and pd.notna(roe_cur) and float(pe_cur) > 0 and float(roe_cur) > 0:
                        out.at[idx, "P_BV"] = round(float(pe_cur) * float(roe_cur) / 100.0, 2)
                    elif derived["P_BV"] is not None:
                        out.at[idx, "P_BV"] = derived["P_BV"]

            if "Rev_Growth_%" in out.columns and pd.isna(out.at[idx, "Rev_Growth_%"]) and derived["Rev_Growth_%"] is not None:
                out.at[idx, "Rev_Growth_%"] = derived["Rev_Growth_%"]
        else:
            for col in ("P_BV", "P_E", "ROE_%", "Rev_Growth_%", "Debt_EBITDA", "FCF_Yield_%"):
                if col in out.columns and pd.isna(out.at[idx, col]) and derived.get(col) is not None:
                    out.at[idx, col] = derived[col]

    return out
