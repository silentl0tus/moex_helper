"""
Foundry Client - Public Financial MCP Server Integration for moex_helper.
Provides resilient, cached access to Data Foundry MCP server (https://mcp.vrednyj-investor.ru/mcp)
with smart dataset version invalidation, IFRS/RAS isolation, auto-variant resolution, and graceful degradation.
"""
from __future__ import annotations

import asyncio
from concurrent.futures import ThreadPoolExecutor
from decimal import Decimal
import logging
from typing import Any, Optional

from mcp import ClientSession
from mcp.client.streamable_http import streamable_http_client
import requests
import streamlit as st

logger = logging.getLogger(__name__)

MCP_URL = "https://mcp.vrednyj-investor.ru/mcp"
HEALTHZ_URL = "https://mcp.vrednyj-investor.ru/healthz"
EXPECTED_SCHEMA_VERSION = 1
TIMEOUT_HEALTHZ = 3.0
TIMEOUT_MCP_CONNECT = 10.0

# Canonical Metric Presets
METRICS_REAL_SECTOR = [
    ("fin.revenue", "Выручка", "RUB"),
    ("fin.operating_profit", "Операционная прибыль", "RUB"),
    ("fin.ebitda", "EBITDA", "RUB"),
    ("fin.net_income", "Чистая прибыль", "RUB"),
    ("fin.cash_and_equivalents", "Денежные средства и эквиваленты", "RUB"),
    ("fin.interest_bearing_debt", "Процентный долг", "RUB"),
    ("fin.total_equity", "Капитал (чистые активы)", "RUB"),
    ("fin.total_assets", "Итого активы", "RUB"),
    ("fin.capex", "Капитальные затраты (CAPEX)", "RUB"),
]

METRICS_BANKING = [
    ("bank.net_interest_income", "Чистый процентный доход", "RUB"),
    ("bank.fee_commission_income", "Комиссионные доходы", "RUB"),
    ("bank.net_fee_commission_income", "Чистый комиссионный доход", "RUB"),
    ("bank.operating_income_after_credit_losses", "Операционный доход после резервов", "RUB"),
    ("fin.net_income", "Чистая прибыль", "RUB"),
    ("fin.total_assets", "Итого активы банка", "RUB"),
    ("fin.total_equity", "Собственный капитал", "RUB"),
]

KNOWN_BANKS = {"SBER", "SBERP", "VTBR", "BSPB", "CBOM", "SVCB", "T", "TCSG", "MBNK"}


class VersionExpiredError(Exception):
    """Raised when server dataset version changed during pagination or query."""
    pass


def _run_async(coro):
    """Safely runs an async coroutine inside sync Streamlit execution threads."""
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        loop = None

    if loop and loop.is_running():
        with ThreadPoolExecutor(max_workers=1) as pool:
            return pool.submit(asyncio.run, coro).result()
    return asyncio.run(coro)


@st.cache_data(ttl=300)
def fetch_moex_market_snapshot(ticker: str) -> dict[str, Any]:
    """Fetches latest market price and capitalization from MOEX ISS TQBR board."""
    if not ticker:
        return {}
    url = f"https://iss.moex.com/iss/engines/stock/markets/shares/boards/TQBR/securities/{ticker.upper()}.json?iss.meta=off"
    try:
        resp = requests.get(url, timeout=4.0)
        if resp.status_code == 200:
            data = resp.json()
            mdata = data.get("marketdata", {})
            cols = mdata.get("columns", [])
            rows = mdata.get("data", [])
            if rows and cols:
                row_dict = dict(zip(cols, rows[0]))
                return {
                    "price": row_dict.get("LAST"),
                    "market_cap": row_dict.get("ISSUECAPITALIZATION"),
                    "change_pct": row_dict.get("LASTTOPREVPRICE"),
                    "volume_rub": row_dict.get("VALTODAY"),
                }
    except Exception as exc:
        logger.debug(f"MOEX market snapshot failed for {ticker}: {exc}")
    return {}


@st.cache_data(ttl=300)
def get_foundry_status() -> dict[str, Any]:
    """
    Checks Data Foundry healthz endpoint. Cached for 5 minutes (TTL=300s).
    Returns dataset version, schema version validation, and build timestamps.
    """
    try:
        resp = requests.get(HEALTHZ_URL, timeout=TIMEOUT_HEALTHZ)
        if resp.status_code == 200:
            data = resp.json()
            dataset = data.get("dataset", {})
            schema_ver = dataset.get("schema_version")
            return {
                "ok": True,
                "status": "ok",
                "dataset_version": dataset.get("version"),
                "schema_version": schema_ver,
                "is_schema_supported": schema_ver == EXPECTED_SCHEMA_VERSION,
                "built_at": dataset.get("built_at"),
                "published_at": dataset.get("published_at"),
                "source_updated_at": dataset.get("source_updated_at"),
                "error": None,
            }
        return {
            "ok": False,
            "status": f"HTTP {resp.status_code}",
            "dataset_version": None,
            "schema_version": None,
            "is_schema_supported": False,
            "error": f"HTTP status {resp.status_code}",
        }
    except Exception as exc:
        logger.warning(f"Data Foundry healthz check failed: {exc}")
        return {
            "ok": False,
            "status": "unreachable",
            "dataset_version": None,
            "schema_version": None,
            "is_schema_supported": False,
            "error": str(exc),
        }


def clear_foundry_cache():
    """Invalidates the healthz cache so the next call queries fresh server status."""
    get_foundry_status.clear()


async def _call_mcp_raw(tool_name: str, arguments: dict) -> dict[str, Any]:
    """Execute a single MCP tool call over Streamable HTTP transport."""
    async with streamable_http_client(MCP_URL) as (read_stream, write_stream):
        async with ClientSession(read_stream, write_stream) as session:
            await session.initialize()
            res = await session.call_tool(tool_name, arguments=arguments)
            
            if hasattr(res, "structured_content") and isinstance(res.structured_content, dict):
                return res.structured_content
            
            for item in res.content:
                if hasattr(item, "text"):
                    import json
                    try:
                        return json.loads(item.text)
                    except Exception:
                        return {"raw_text": item.text}
            return {}


async def _fetch_paginated_mcp(tool_name: str, args: dict, max_pages: int = 5) -> list[dict[str, Any]]:
    """Fetches paginated items using next_cursor handling."""
    all_items = []
    current_args = dict(args)
    
    for _ in range(max_pages):
        payload = await _call_mcp_raw(tool_name, current_args)
        status = payload.get("status")
        
        if status == "version_expired" or "version_expired" in str(payload.get("message", "")).lower():
            clear_foundry_cache()
            raise VersionExpiredError("Server dataset version expired. Refetched healthz.")
        
        # If ambiguous, select first choice variant
        if status == "ambiguous" and payload.get("choices"):
            first_choice = payload["choices"][0]
            var_id = first_choice.get("variant") or first_choice.get("selector")
            if var_id:
                current_args["variants"] = [var_id]
                payload = await _call_mcp_raw(tool_name, current_args)
                status = payload.get("status")

        if status not in ("ok", None):
            logger.warning(f"MCP tool {tool_name} returned non-ok status: {status}, msg: {payload.get('message')}")
            break
            
        items = payload.get("items", [])
        all_items.extend(items)
        
        page = payload.get("page", {})
        next_cursor = page.get("next_cursor")
        if not next_cursor or page.get("returned", 0) == 0:
            break
        current_args["cursor"] = next_cursor
        
    return all_items


# ==============================================================================
# Cached MCP Query Functions (No TTL - keyed by dataset_version)
# ==============================================================================

@st.cache_data
def search_companies(query_text: str, dataset_version: Optional[str]) -> list[dict[str, Any]]:
    """Search companies by ticker or name. Cached infinitely per dataset_version."""
    if not dataset_version or not query_text:
        return []
    try:
        return _run_async(_fetch_paginated_mcp("search_companies", {"query_text": query_text, "limit": 20}))
    except VersionExpiredError:
        fresh_status = get_foundry_status()
        new_ver = fresh_status.get("dataset_version")
        if new_ver and new_ver != dataset_version:
            return search_companies(query_text, new_ver)
        return []
    except Exception as exc:
        logger.error(f"Error in search_companies({query_text}): {exc}")
        return []


@st.cache_data
def find_metrics(query_text: str, companies: tuple[str, ...], dataset_version: Optional[str]) -> list[dict[str, Any]]:
    """Search metric definitions. Cached infinitely per dataset_version."""
    if not dataset_version or not query_text:
        return []
    args: dict[str, Any] = {"query_text": query_text, "limit": 50}
    if companies:
        args["companies"] = list(companies)
    try:
        return _run_async(_fetch_paginated_mcp("find_metrics", args))
    except VersionExpiredError:
        fresh_status = get_foundry_status()
        new_ver = fresh_status.get("dataset_version")
        if new_ver and new_ver != dataset_version:
            return find_metrics(query_text, companies, new_ver)
        return []
    except Exception as exc:
        logger.error(f"Error in find_metrics({query_text}): {exc}")
        return []


@st.cache_data
def get_series(
    companies: tuple[str, ...],
    metrics: tuple[str, ...],
    periods: Optional[tuple[str, ...]],
    dataset_version: Optional[str],
    revisions: str = "current"
) -> list[dict[str, Any]]:
    """
    Fetch financial series. To prevent cross-metric ambiguity clashes,
    queries are executed per company/metric with automatic variant resolution.
    """
    if not dataset_version or not companies or not metrics:
        return []
    
    async def _fetch_all_metrics():
        async with streamable_http_client(MCP_URL) as (read_stream, write_stream):
            async with ClientSession(read_stream, write_stream) as session:
                await session.initialize()
                
                async def _fetch_single(co: str, m: str):
                    call_args: dict[str, Any] = {
                        "companies": [co],
                        "metrics": [m],
                        "revisions": revisions,
                        "limit": 100,
                    }
                    if periods:
                        call_args["periods"] = list(periods)
                        
                    res = await session.call_tool("get_series", arguments=call_args)
                    import json
                    try:
                        data = json.loads(res.content[0].text)
                    except Exception:
                        return []
                    
                    if data.get("status") == "ambiguous" and data.get("choices"):
                        merged_items = []
                        # Query each choice variant and merge
                        for choice in data["choices"][:3]:
                            var = choice.get("variant") or choice.get("selector")
                            if var:
                                call_args["variants"] = [var]
                                res_v = await session.call_tool("get_series", arguments=call_args)
                                try:
                                    data_v = json.loads(res_v.content[0].text)
                                    merged_items.extend(data_v.get("items", []))
                                except Exception:
                                    pass
                        # Deduplicate preferring group geography
                        by_period: dict[str, dict[str, Any]] = {}
                        for item in merged_items:
                            pkey = item.get("period", {}).get("key")
                            if pkey not in by_period or (item.get("dimensions", {}).get("geography") == "group"):
                                by_period[pkey] = item
                        return list(by_period.values())
                                
                    return data.get("items", [])
                
                tasks = [
                    _fetch_single(co, m)
                    for co in companies[:10]
                    for m in metrics[:20]
                ]
                results = await asyncio.gather(*tasks, return_exceptions=True)
                combined = []
                for r in results:
                    if isinstance(r, list):
                        combined.extend(r)
                return combined

    try:
        return _run_async(_fetch_all_metrics())
    except VersionExpiredError:
        fresh_status = get_foundry_status()
        new_ver = fresh_status.get("dataset_version")
        if new_ver and new_ver != dataset_version:
            return get_series(companies, metrics, periods, new_ver, revisions)
        return []
    except Exception as exc:
        logger.error(f"Error in get_series({companies}, {metrics}): {exc}")
        return []


@st.cache_data
def get_coverage(
    companies: tuple[str, ...],
    metrics: tuple[str, ...],
    periods: Optional[tuple[str, ...]],
    dataset_version: Optional[str]
) -> list[dict[str, Any]]:
    """Fetch availability coverage and missing periods."""
    if not dataset_version or not companies or not metrics:
        return []
    args: dict[str, Any] = {
        "companies": list(companies[:10]),
        "metrics": list(metrics[:20]),
        "limit": 100
    }
    if periods:
        args["periods"] = list(periods[:40])
    try:
        return _run_async(_fetch_paginated_mcp("get_coverage", args))
    except VersionExpiredError:
        fresh_status = get_foundry_status()
        new_ver = fresh_status.get("dataset_version")
        if new_ver and new_ver != dataset_version:
            return get_coverage(companies, metrics, periods, new_ver)
        return []
    except Exception as exc:
        logger.error(f"Error in get_coverage: {exc}")
        return []


@st.cache_data
def get_evidence(source_ids: tuple[str, ...], dataset_version: Optional[str]) -> dict[str, dict[str, Any]]:
    """
    Fetch evidence (document title, locator page/row, sha256) by source_id.
    Returns mapping: source_id -> evidence dict.
    """
    if not dataset_version or not source_ids:
        return {}
    
    evidence_map: dict[str, dict[str, Any]] = {}
    chunk_size = 20
    for i in range(0, len(source_ids), chunk_size):
        chunk = list(source_ids[i:i + chunk_size])
        try:
            items = _run_async(_fetch_paginated_mcp("get_evidence", {"source_ids": chunk, "limit": 100}))
            for item in items:
                sid = item.get("source_id")
                if sid:
                    evidence_map[sid] = item
        except VersionExpiredError:
            fresh_status = get_foundry_status()
            new_ver = fresh_status.get("dataset_version")
            if new_ver and new_ver != dataset_version:
                return get_evidence(source_ids, new_ver)
            break
        except Exception as exc:
            logger.error(f"Error in get_evidence chunk: {exc}")
            
    return evidence_map


# ==============================================================================
# High-Level Profile Aggregator & Standards Separation
# ==============================================================================

def to_float_or_none(val: Any) -> Optional[float]:
    """Safe conversion of exact decimal string to float without converting None to 0."""
    if val is None:
        return None
    try:
        return float(Decimal(str(val)))
    except Exception:
        return None


def normalize_period_key(period_dict: dict[str, Any]) -> str:
    """
    Normalizes point-in-time (ASOF:YYYY-MM-DD) and duration (YYYY-FY, YYYY-H1) period keys
    so balance sheet and income statement metrics align on identical reporting columns.
    """
    if not period_dict:
        return ""
    key = period_dict.get("key", "")
    if period_dict.get("kind") == "instant" or key.startswith("ASOF:"):
        year = period_dict.get("calendar_year")
        end = str(period_dict.get("end", ""))
        if not year and ":" in key:
            try:
                year = key.split(":")[1].split("-")[0]
            except Exception:
                year = ""
        if end.endswith("-12-31") or period_dict.get("group") == "annual":
            return f"{year}-FY" if year else key
        elif end.endswith("-06-30") or end.endswith("-07-01"):
            return f"{year}-H1" if year else key
        elif end.endswith("-09-30"):
            return f"{year}-9M" if year else key
        elif end.endswith("-03-31"):
            return f"{year}-Q1" if year else key
    return key


def get_company_fundamental_profile(
    ticker: str,
    dataset_version: Optional[str],
    accounting_basis: str = "IFRS",
    target_years: Optional[list[int]] = None
) -> dict[str, Any]:
    """
    High-level aggregator for a company ticker:
    1. Identifies industry sector (banking vs real sector).
    2. Fetches series strictly for requested accounting_basis (default 'IFRS').
    3. Aligns duration and instant reporting periods.
    4. Handles missing periods (2022-2023) leaving None intact (NEVER substituting 0).
    5. Retrieves evidence details for data provenance.
    """
    if not dataset_version or not ticker:
        return {"error": "Missing ticker or dataset_version", "items": [], "periods": []}

    norm_ticker = ticker.strip().upper()
    
    # 1. Company Search & Industry identification
    search_res = search_companies(norm_ticker, dataset_version)
    matched_company = None
    for comp in search_res:
        if comp.get("ticker") == norm_ticker:
            matched_company = comp
            break
    if not matched_company and search_res:
        matched_company = search_res[0]
        
    is_bank = (
        norm_ticker in KNOWN_BANKS or 
        (matched_company and matched_company.get("industry") == "bank")
    )

    preset_tuples = METRICS_BANKING if is_bank else METRICS_REAL_SECTOR
    metric_codes = tuple(m[0] for m in preset_tuples)

    # Generate standard query periods (both duration and ASOF equivalents)
    if not target_years:
        target_years = [2021, 2022, 2023, 2024, 2025, 2026]
        
    query_periods = []
    for y in target_years:
        query_periods.extend([
            f"{y}-FY", f"ASOF:{y}-12-31",
            f"{y}-H1", f"ASOF:{y}-06-30",
        ])

    # 2. Fetch Series
    series_raw = get_series(
        companies=(norm_ticker,),
        metrics=metric_codes,
        periods=tuple(query_periods),
        dataset_version=dataset_version,
        revisions="current"
    )

    # 3. Discover available accounting standards
    available_standards = sorted(list({
        item.get("accounting_basis") for item in series_raw if item.get("accounting_basis")
    }))
    
    # If chosen standard has no data but other standards do, we note it
    allowed_bases = ("IFRS", "APM") if accounting_basis == "IFRS" else (accounting_basis,)
    filtered_series = [
        item for item in series_raw
        if item.get("accounting_basis") in allowed_bases and item.get("ticker") == norm_ticker
    ]

    # 4. Map normalized periods
    # Collect all unique normalized period keys present in data
    seen_periods = set()
    for item in filtered_series:
        norm_key = normalize_period_key(item.get("period", {}))
        if norm_key and norm_key.endswith(("-FY", "-H1")):
            seen_periods.add(norm_key)

    # Sort periods chronologically
    def period_sort_key(k: str):
        parts = k.split("-")
        year = int(parts[0]) if parts[0].isdigit() else 0
        suffix = parts[1] if len(parts) > 1 else ""
        order = {"H1": 1, "FY": 2}
        return (year, order.get(suffix, 3), k)

    sorted_periods = sorted(seen_periods, key=period_sort_key)
    # Take last 6 available periods for clean tabular view
    display_periods = sorted_periods[-6:] if len(sorted_periods) > 6 else sorted_periods

    # 5. Populate matrix: metric_code -> normalized_period_key -> item
    matrix: dict[str, dict[str, Any]] = {code: {} for code in metric_codes}
    source_ids_to_fetch = set()

    for item in filtered_series:
        m_code = item.get("metric_code")
        norm_key = normalize_period_key(item.get("period", {}))
        if m_code in matrix and norm_key in display_periods:
            matrix[m_code][norm_key] = item
            sid = item.get("source_id")
            if sid:
                source_ids_to_fetch.add(sid)

    # 6. Fetch Evidence
    evidence_map = {}
    if source_ids_to_fetch:
        evidence_map = get_evidence(tuple(source_ids_to_fetch), dataset_version)

    # 7. Build structured rows
    rows = []
    for code, name, unit in preset_tuples:
        period_data = matrix.get(code, {})
        row: dict[str, Any] = {
            "metric_code": code,
            "metric_name": name,
            "unit": unit,
            "values": {},          # norm_key -> float or None (NEVER 0 for missing!)
            "raw_items": {},       # norm_key -> raw MCP item
            "evidence": {},        # norm_key -> evidence dict
            "methodology": None,
        }
        for p_key in display_periods:
            item = period_data.get(p_key)
            if item:
                val = to_float_or_none(item.get("value"))
                row["values"][p_key] = val
                row["raw_items"][p_key] = item
                sid = item.get("source_id")
                if sid and sid in evidence_map:
                    row["evidence"][p_key] = evidence_map[sid]
                if not row["methodology"] and item.get("methodology"):
                    row["methodology"] = item.get("methodology")
            else:
                # STRICT RULE: Missing is None, NEVER 0!
                row["values"][p_key] = None
                row["raw_items"][p_key] = None
        rows.append(row)

    # 8. Derived calculations (Only when components are present)
    derived_rows = []
    # Real sector: Net Debt
    if not is_bank and "fin.interest_bearing_debt" in matrix and "fin.cash_and_equivalents" in matrix:
        net_debt_values = {}
        for p_key in display_periods:
            debt_item = matrix["fin.interest_bearing_debt"].get(p_key)
            cash_item = matrix["fin.cash_and_equivalents"].get(p_key)
            debt_val = to_float_or_none(debt_item.get("value")) if debt_item else None
            cash_val = to_float_or_none(cash_item.get("value")) if cash_item else None
            if debt_val is not None and cash_val is not None:
                net_debt_values[p_key] = debt_val - cash_val
            else:
                net_debt_values[p_key] = None
        
        derived_rows.append({
            "metric_code": "calc.net_debt",
            "metric_name": "Чистый долг (Долг − ДС)",
            "unit": "RUB",
            "values": net_debt_values,
            "raw_items": {},
            "evidence": {},
            "methodology": {
                "name": "Расчётный чистый долг",
                "formula": "Процентный долг (fin.interest_bearing_debt) − Денежные средства (fin.cash_and_equivalents)"
            }
        })

    # ROE Calculation: Net Income / Total Equity
    if "fin.net_income" in matrix and "fin.total_equity" in matrix:
        roe_values = {}
        for p_key in display_periods:
            ni_item = matrix["fin.net_income"].get(p_key)
            eq_item = matrix["fin.total_equity"].get(p_key)
            ni_val = to_float_or_none(ni_item.get("value")) if ni_item else None
            eq_val = to_float_or_none(eq_item.get("value")) if eq_item else None
            if ni_val is not None and eq_val is not None and eq_val > 0:
                roe_values[p_key] = round((ni_val / eq_val) * 100, 2)
            else:
                roe_values[p_key] = None
        
        derived_rows.append({
            "metric_code": "calc.roe",
            "metric_name": "ROE (Рентабельность капитала, %)",
            "unit": "%",
            "values": roe_values,
            "raw_items": {},
            "evidence": {},
            "methodology": {
                "name": "Расчётный ROE",
                "formula": "(Чистая прибыль / Собственный капитал) × 100%"
            }
        })

    # Net Margin: Net Income / Revenue (for real sector)
    if not is_bank and "fin.net_income" in matrix and "fin.revenue" in matrix:
        margin_values = {}
        for p_key in display_periods:
            ni_item = matrix["fin.net_income"].get(p_key)
            rev_item = matrix["fin.revenue"].get(p_key)
            ni_val = to_float_or_none(ni_item.get("value")) if ni_item else None
            rev_val = to_float_or_none(rev_item.get("value")) if rev_item else None
            if ni_val is not None and rev_val is not None and rev_val > 0:
                margin_values[p_key] = round((ni_val / rev_val) * 100, 2)
            else:
                margin_values[p_key] = None
        
        derived_rows.append({
            "metric_code": "calc.net_margin",
            "metric_name": "Чистая рентабельность (Net Margin, %)",
            "unit": "%",
            "values": margin_values,
            "raw_items": {},
            "evidence": {},
            "methodology": {
                "name": "Чистая маржа",
                "formula": "(Чистая прибыль / Выручка) × 100%"
            }
        })

    all_rows = rows + derived_rows

    return {
        "ticker": norm_ticker,
        "company_name": matched_company.get("name") if matched_company else norm_ticker,
        "industry": matched_company.get("industry") if matched_company else ("bank" if is_bank else None),
        "is_bank": is_bank,
        "accounting_basis": accounting_basis,
        "available_standards": available_standards,
        "periods": display_periods,
        "rows": all_rows,
        "evidence_map": evidence_map,
        "dataset_version": dataset_version,
    }
