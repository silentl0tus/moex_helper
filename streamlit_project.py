import json
import math
import os
import re
from datetime import datetime, timedelta
from io import StringIO, BytesIO
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor

import altair as alt
import pandas as pd
import requests
import yfinance as yf
import streamlit as st
st.set_page_config(page_title="Экран инвестора | MOEX Helper", page_icon="📊", layout="wide")

st.markdown("""
<style>
    /* Переименование ссылки на главную страницу в боковом меню */
    [data-testid="stSidebarNav"] li:first-child a span,
    [data-testid="stSidebarNavItems"] li:first-child a span {
        display: none !important;
    }
    [data-testid="stSidebarNav"] li:first-child a::after,
    [data-testid="stSidebarNavItems"] li:first-child a::after {
        content: "📊 Экран инвестора";
        font-size: 0.875rem;
        font-weight: 500;
    }

    /* =================================================================
       ОПТИМИЗАЦИЯ ДЛЯ СМАРТФОНОВ И УСТРАНЕНИЕ ЛАГОВ РЕНДЕРИНГА (MWG)
       ================================================================= */
    /* Базовая изоляция стилей и плавный нативный тач-скролл */
    html, body {
        -webkit-tap-highlight-color: transparent;
        scroll-behavior: smooth;
    }

    /* Изоляция отрисовки вкладок (CSS Containment) для ускорения DOM */
    [data-testid="stTabsContent"] {
        contain: layout style;
    }

    @supports not (content-visibility: auto) {
        [data-testid="stTabsContent"] {
            contain: layout style paint;
        }
    }

    /* Адаптивность и защита от лагов на экранах смартфонов (ширина <= 768px) */
    @media (max-width: 768px) {
        /* Разворачиваем сжатые 3-4-5 колоночные блоки в вертикальный стек */
        [data-testid="stHorizontalBlock"] {
            flex-wrap: wrap !important;
            gap: 0.4rem !important;
        }
        [data-testid="stHorizontalBlock"] > [data-testid="stColumn"] {
            min-width: 100% !important;
            flex: 1 1 100% !important;
        }

        /* Блоки с метриками (st.metric) группируем аккуратно по 2 в ряд */
        [data-testid="stHorizontalBlock"]:has([data-testid="stMetric"]) > [data-testid="stColumn"] {
            min-width: calc(50% - 0.25rem) !important;
            flex: 1 1 calc(50% - 0.25rem) !important;
        }

        /* Компактный вид метрик для экономии места на AMOLED экране */
        [data-testid="stMetric"] {
            padding: 5px 8px !important;
            background: rgba(255, 255, 255, 0.02) !important;
            border-radius: 8px !important;
        }
        [data-testid="stMetricLabel"] {
            font-size: 0.76rem !important;
        }
        [data-testid="stMetricValue"] {
            font-size: 1.15rem !important;
            line-height: 1.2 !important;
        }
        [data-testid="stMetricDelta"] {
            font-size: 0.72rem !important;
        }

        /* Уменьшение отступов карточек и контейнеров */
        [data-testid="stVerticalBlockBorderWrapper"] {
            padding: 8px !important;
            margin-bottom: 6px !important;
            border-radius: 8px !important;
        }

        /* Горизонтальный скролл таблиц без распирания страницы */
        [data-testid="stDataFrame"] {
            max-width: 100% !important;
            overflow-x: auto !important;
            -webkit-overflow-scrolling: touch;
        }

        /* Перенос кнопок в горизонтальных радио-группах */
        div[role="radiogroup"] {
            flex-wrap: wrap !important;
            gap: 4px !important;
        }

        /* Прокрутка списка вкладок при переполнении */
        .stTabs [data-baseweb="tab-list"] {
            overflow-x: auto !important;
            white-space: nowrap !important;
            -webkit-overflow-scrolling: touch;
        }

        /* Предотвращение блокировки вертикального скролла графиками Vega/Altair на смартфоне */
        .vega-embed, .vega-embed canvas, .vega-embed svg {
            touch-action: pan-y !important;
        }
    }

    /* На тач-устройствах отключаем лишние задержки анимаций */
    @media (hover: none), (pointer: coarse) {
        * {
            -webkit-tap-highlight-color: transparent;
        }
    }
</style>
""", unsafe_allow_html=True)

from moexalgo import Ticker
from src.market_screener import (
    fetch_market_screener_data,
    fetch_commodities_barometer,
    render_market_view_component
)
from src.foundry_client import (
    get_foundry_status,
    clear_foundry_cache,
    get_company_fundamental_profile,
    fetch_moex_market_snapshot,
)
from src.black_line import (
    calculate_black_line_valuation,
    render_black_line_widget,
    fetch_stock_candles,
)
from src.izi_mcp_client import get_izi_config, get_user_portfolios
from src.portfolio_importer import fetch_izi_mcp_portfolio

PORTFOLIO_TICKERS = [
    "MGNT", "SBER", "ROSN", "NMTP", "SVCB",
    "T", "SIBN", "BELU", "CHMF", "NLMK",
    "SNGS", "TRNFP", "GAZP"
]

# ==========================================
# 1. СИСТЕМНЫЕ НАСТРОЙКИ
# ==========================================
st.title("📊 Экран инвестора")
st.caption("Комплексный дашборд: цены с MOEX, фундаментал, Health Score, макро-часы и аудит портфеля")

with st.expander("📖 Как эффективно использовать этот дашборд", expanded=False):
    st.markdown("""
    **1. Загрузите свой текущий портфель (слева)**  
    Загрузите выгрузку из брокера (Excel/CSV) или Snowball Income. Дашборд автоматически:
    * Отделит заблокированные активы и облигации от акций.
    * Посчитает реальный свободный кэш и покажет PnL по облигациям.
    
    **2. Укажите макроэкономическую фазу**  
    В блоке "Макроэкономика и Часы" выберите текущую фазу (например, *Стагфляция*). Это автоматически настроит алгоритм под текущий цикл рынка: цикличные компании получат штраф, а защитные (например, с кэшем) — бонус.
    
    **3. Отрегулируйте риск-менеджмент**  
    Укажите размер вашего капитала и комфортное количество акций в портфеле. Алгоритм рассчитает идеальную долю (вес) для каждой акции, чтобы вы не взяли на себя слишком много риска в одном активе.
    
    **4. Изучите итоговый рейтинг (Health Score)**  
    В таблице **«Рейтинг и ребалансировка»** акции отсортированы по комплексному баллу здоровья. Этот балл учитывает:
    * **Эффективность (ROE)** — как хорошо компания генерирует прибыль.
    * **Оценку (P/E)** — насколько дешево стоит бизнес.
    * **Долг (Debt/EBITDA)** — штраф за высокие долги (что критично при высокой ставке ЦБ) и премия за свободные деньги на счетах.
    * **Темпы роста** — премия за растущую выручку.
    
    Сравнив колонку *«Идеальная доля»* с *«Текущая доля»*, вы сразу увидите математически обоснованные сигналы: какие акции стоит **докупить**, а какие — **сократить** или продать.
    """)

MIN_DAILY_TURNOVER_RUB = 50_000_000
MOEX_TQBR_URL = "https://iss.moex.com/iss/engines/stock/markets/shares/boards/TQBR/securities.json"
REQUIRED_FUNDAMENTALS = ["ROE_%", "P_E", "Debt_EBITDA"]

# -- Классификация тикеров по секторам (единственное определение) --
BANK_TICKERS     = ['SBER', 'SBERP', 'VTBR', 'TCSG', 'BSPB', 'CBOM', 'T', 'SVCB']
IT_TICKERS       = ['ASTR', 'POSI', 'DIAS', 'DATA', 'SOFL', 'VKCO', 'YNDX', 'HEAD', 'OZON']
OIL_TICKERS      = ['ROSN', 'LKOH', 'SIBN', 'TATN', 'TATNP', 'SNGS', 'SNGSP', 'TRNFP', 'BANE', 'BANEP', 'RNFT']
STEEL_TICKERS    = ['CHMF', 'NLMK', 'MAGN']
GOLD_TICKERS     = ['PLZL', 'UGC', 'SELG']
CONSUMER_TICKERS = ['MGNT', 'FIVE', 'FIXP', 'OBUV', 'ORUP', 'BELU', 'AQUA']
TELECOM_TICKERS  = ['MTSS', 'RTKM', 'RTKMP']
UTILITIES_TICKERS = ['IRAO', 'UPRO', 'HYDR', 'MSNG', 'FEES', 'LSNG', 'LSNGP']
CYCLICAL_TICKERS = ['CHMF', 'NLMK', 'MAGN', 'ALRS', 'PLZL', 'UGC', 'MTLR', 'RASP', 'SELG']
# Структурный дисконт: вечно дешёвый P/BV и закрытая кубышка / госкапекс (без иллюзии 3/PBV)
STRUCTURAL_DISCOUNT_TICKERS = ['SNGS', 'SNGSP', 'GAZP', 'FEES', 'UPRO']
# Классические холдинги: P/E искажён переоценками дочек (без Сургута и Газпрома)
HOLDING_TICKERS  = ['AFKS', 'SFIN', 'ENPG']
ZERO_DEBT_TICKERS = ['SNGS', 'SNGSP']  # отрицательный чистый долг
# Чёрный список: предбанкроты, уход с биржи, плохое корп. управление, дистресс-активы
TOXIC_TICKERS    = ['PIKK', 'SMLT', 'EUTR', 'QIWI', 'POLY', 'ORUP', 'OBUV', 'RUGR', 'FIXP', 'CBOM', 'SGZH', 'MTLR', 'MTLRP']

# ==========================================
# 2. ФУНКЦИИ СБОРА ДАННЫХ
# ==========================================
def _fetch_candles(asset, start_date, end_date):
    candles_method = getattr(asset, "candles", None)
    if not callable(candles_method):
        raise AttributeError("moexalgo Ticker не предоставляет метод candles")

    raw_candles = candles_method(start=start_date.isoformat(), end=end_date.isoformat(), period="1D")
    if isinstance(raw_candles, pd.DataFrame):
        return raw_candles.copy()
    if isinstance(raw_candles, (list, tuple)):
        return pd.DataFrame(raw_candles)
    if raw_candles is None:
        return pd.DataFrame()
    try:
        return pd.DataFrame(raw_candles)
    except Exception:
        return pd.DataFrame()

_MOEX_UNIVERSE_CACHE_PATH = Path(os.path.abspath(__file__)).parent / "data" / "moex_universe_cache.json"


@st.cache_data(ttl=90, show_spinner=False)
def _is_moex_iss_reachable() -> bool:
    """Быстрая проверка доступности MOEX ISS (предотвращает каскадные зависания по 30s+ при таймаутах)."""
    try:
        resp = requests.get(
            "https://iss.moex.com/iss/index.json?iss.meta=off&iss.only=engines",
            timeout=(4.0, 4.0),
        )
        return resp.status_code < 500
    except Exception:
        return False


def _build_moex_universe_df(data: dict, min_turnover_rub: int, ignore_liquidity: bool, is_fallback: bool = False) -> pd.DataFrame:
    """Формирует отсортированный DataFrame вселенной тикеров MOEX из ответа ISS API или кэша."""
    turnover_by_ticker = {
        row[0]: row[1] or 0
        for row in data.get("marketdata", {}).get("data", [])
        if row and row[0]
    }
    max_turnover = max(turnover_by_ticker.values()) if turnover_by_ticker else 0
    market_is_open = max_turnover > min_turnover_rub

    rows = []
    for ticker, list_level in data.get("securities", {}).get("data", []):
        if not ticker:
            continue
        if list_level not in (1, 2) and ticker not in PORTFOLIO_TICKERS:
            continue
        turnover_rub = turnover_by_ticker.get(ticker, 0)
        if not ignore_liquidity and market_is_open and turnover_rub < min_turnover_rub and ticker not in PORTFOLIO_TICKERS:
            continue
        rows.append(
            {
                "ticker": ticker,
                "list_level": list_level,
                "turnover_rub": turnover_rub,
                "turnover_mln": round(turnover_rub / 1_000_000, 1),
            }
        )

    df = pd.DataFrame(rows, columns=["ticker", "list_level", "turnover_rub", "turnover_mln"])
    if df.empty:
        return _build_static_fallback_universe(is_fallback=True)
    df = df.sort_values("turnover_rub", ascending=False).reset_index(drop=True)
    df.attrs["is_fallback"] = is_fallback
    return df


def _build_static_fallback_universe(is_fallback: bool = True) -> pd.DataFrame:
    """Формирует резервный список тикеров из fundamentals_cache.csv + PORTFOLIO_TICKERS без обращения к сети."""
    tickers = list(PORTFOLIO_TICKERS)
    cache_csv = Path(os.path.abspath(__file__)).parent / "fundamentals_cache.csv"
    if cache_csv.exists():
        try:
            df_c = pd.read_csv(cache_csv)
            for t in df_c["ticker"].dropna().astype(str).str.upper().unique():
                if t not in tickers:
                    tickers.append(t)
        except Exception:
            pass

    rows = [
        {
            "ticker": t,
            "list_level": 1,
            "turnover_rub": 100_000_000 if t in PORTFOLIO_TICKERS else 60_000_000,
            "turnover_mln": 100.0 if t in PORTFOLIO_TICKERS else 60.0,
        }
        for t in tickers
    ]
    df = pd.DataFrame(rows, columns=["ticker", "list_level", "turnover_rub", "turnover_mln"])
    df.attrs["is_fallback"] = is_fallback
    return df


@st.cache_data(ttl=600)
def fetch_live_prices(ticker_list):
    if not ticker_list or not _is_moex_iss_reachable():
        return pd.DataFrame()

    end_date = datetime.now().date()
    start_date = end_date - timedelta(days=120)
    price_series = {}

    def _fetch_single(t):
        try:
            asset = Ticker(t)
            candles_df = _fetch_candles(asset, start_date, end_date)
            if candles_df is not None and not candles_df.empty and "close" in candles_df.columns:
                series = candles_df["close"].astype(float)
                if "begin" in candles_df.columns:
                    series.index = pd.to_datetime(candles_df["begin"])
                else:
                    series.index = pd.to_datetime(series.index)
                return t, series
        except Exception:
            pass
        return t, None

    workers = min(10, max(1, len(ticker_list)))
    with ThreadPoolExecutor(max_workers=workers) as executor:
        results = list(executor.map(_fetch_single, ticker_list))

    for t, series in results:
        if series is not None:
            price_series[t] = series

    if not price_series:
        return pd.DataFrame()

    return pd.DataFrame(price_series).sort_index().dropna(how="all")

def normalize_returns(price_df):
    return price_df.apply(
        lambda series: (series / series.dropna().iloc[0] - 1) * 100
        if series.notna().any()
        else series
    )

@st.cache_data(ttl=600, show_spinner=False)
def _fetch_moex_universe_live(min_turnover_rub=MIN_DAILY_TURNOVER_RUB, ignore_liquidity=False):
    params = {
        "iss.meta": "off",
        "iss.only": "securities,marketdata",
        "securities.columns": "SECID,LISTLEVEL",
        "marketdata.columns": "SECID,VALTODAY",
    }
    response = requests.get(MOEX_TQBR_URL, params=params, timeout=(5.0, 12.0))
    response.raise_for_status()
    data = response.json()
    try:
        _MOEX_UNIVERSE_CACHE_PATH.parent.mkdir(parents=True, exist_ok=True)
        _MOEX_UNIVERSE_CACHE_PATH.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    except Exception:
        pass
    return _build_moex_universe_df(data, min_turnover_rub, ignore_liquidity, is_fallback=False)


def fetch_moex_universe(min_turnover_rub=MIN_DAILY_TURNOVER_RUB, ignore_liquidity=False):
    if _is_moex_iss_reachable():
        try:
            df = _fetch_moex_universe_live(min_turnover_rub=min_turnover_rub, ignore_liquidity=ignore_liquidity)
            if df is not None and not df.empty:
                return df
        except Exception:
            pass

    if _MOEX_UNIVERSE_CACHE_PATH.exists():
        try:
            cached_data = json.loads(_MOEX_UNIVERSE_CACHE_PATH.read_text(encoding="utf-8"))
            return _build_moex_universe_df(cached_data, min_turnover_rub, ignore_liquidity, is_fallback=True)
        except Exception:
            pass

    return _build_static_fallback_universe(is_fallback=True)

@st.cache_data(ttl=600)
def fetch_moex_tickers(min_turnover_rub=MIN_DAILY_TURNOVER_RUB, ignore_liquidity=False):
    return fetch_moex_universe(min_turnover_rub=min_turnover_rub, ignore_liquidity=ignore_liquidity)["ticker"].tolist()

@st.cache_data(ttl=600)
def fetch_market_context():
    context = {}
    moex_ok = _is_moex_iss_reachable()

    def _get_moex_symbol(symbol):
        if not moex_ok:
            return symbol, None
        try:
            asset = Ticker(symbol)
            candles_df = _fetch_candles(asset, datetime.now().date() - timedelta(days=30), datetime.now().date())
            if not candles_df.empty and "close" in candles_df.columns:
                return symbol, float(candles_df["close"].iloc[-1])
        except Exception:
            pass
        return symbol, None

    def _get_urals():
        try:
            url = "https://tankermap.com/market-data/urals"
            headers = {"User-Agent": "Mozilla/5.0"}
            response = requests.get(url, headers=headers, timeout=3)
            price_matches = re.findall(r'\$\s*(\d{2,3}\.\d{2})', response.text)
            if price_matches:
                return "URALS", float(price_matches[0])
        except Exception:
            pass
        return "URALS", None

    def _get_cbr_rate():
        try:
            url_cbr = "https://cbr.ru/hd_base/KeyRate/"
            headers = {"User-Agent": "Mozilla/5.0"}
            resp_cbr = requests.get(url_cbr, headers=headers, timeout=3)
            rate_match = re.search(r'<td>(\d{2}[,.]\d{2})</td>', resp_cbr.text)
            if rate_match:
                return "KEY_RATE", float(rate_match.group(1).replace(',', '.'))
        except Exception:
            pass
        return "KEY_RATE", 16.0

    def _get_cbr_inf():
        try:
            url_cbr_main = "https://cbr.ru/"
            headers = {"User-Agent": "Mozilla/5.0"}
            resp_cbr_main = requests.get(url_cbr_main, headers=headers, timeout=3)
            inf_match = re.search(r'Инфляция.*?(\d{1,2}[,.]\d{1,2})\s*%', resp_cbr_main.text, re.IGNORECASE | re.DOTALL)
            if inf_match:
                official_inf = float(inf_match.group(1).replace(',', '.'))
                return "INFLATION_OFFICIAL", official_inf, official_inf + 4.0
        except Exception:
            pass
        return "INFLATION_OFFICIAL", 8.0, 12.0

    def _get_commodity_yf():
        res = {"GOLD": None, "STEEL": None}
        # Используем period="5d", чтобы на выходных/праздниках не получать пустой ответ за 1d
        for key, sym in [("GOLD", "GC=F"), ("STEEL", "HRC=F")]:
            try:
                hist = yf.Ticker(sym).history(period="5d")
                if not hist.empty and "Close" in hist.columns:
                    res[key] = float(hist["Close"].dropna().iloc[-1])
            except Exception:
                pass
        return res

    with ThreadPoolExecutor(max_workers=7) as executor:
        f_moex = [executor.submit(_get_moex_symbol, s) for s in ["IMOEX", "RTSI", "USD000UTSTOM"]]
        f_urals = executor.submit(_get_urals)
        f_rate = executor.submit(_get_cbr_rate)
        f_inf = executor.submit(_get_cbr_inf)
        f_comm = executor.submit(_get_commodity_yf)

    for f in f_moex:
        sym, val = f.result()
        context[sym] = val
    _, context["URALS"] = f_urals.result()
    _, context["KEY_RATE"] = f_rate.result()
    _, context["INFLATION_OFFICIAL"], context["INFLATION_REAL"] = f_inf.result()
    comm_res = f_comm.result()
    context.update(comm_res)

    return context

@st.cache_data(ttl=3600)
def fetch_technical_indicators(tickers):
    cols = ["ticker", "SMA_50", "SMA_200", "RSI", "Price"]
    if not tickers or not _is_moex_iss_reachable():
        return pd.DataFrame(columns=cols)

    def calculate_rsi(series, period=14):
        delta = series.diff()
        gain = (delta.where(delta > 0, 0)).rolling(window=period).mean()
        loss = (-delta.where(delta < 0, 0)).rolling(window=period).mean()
        rs = gain / loss
        return 100 - (100 / (1 + rs))

    def get_ticker_tech(ticker):
        one_year_ago = (datetime.now() - timedelta(days=365)).strftime("%Y-%m-%d")
        url = f"https://iss.moex.com/iss/engines/stock/markets/shares/boards/TQBR/securities/{ticker}/candles.json"
        params = {"interval": 24, "from": one_year_ago}
        try:
            resp = requests.get(url, params=params, timeout=(4.0, 6.0))
            data = resp.json()
            if 'candles' in data and data['candles']['data']:
                df = pd.DataFrame(data['candles']['data'], columns=data['candles']['columns'])
                close = pd.to_numeric(df['close'], errors='coerce').dropna()
                if close.empty:
                    return {"ticker": ticker, "SMA_50": float('nan'), "SMA_200": float('nan'), "RSI": float('nan'), "Price": float('nan')}
                if ticker.upper() in ["BELU", "NOVA"] and 'begin' in df.columns:
                    b_dates = pd.to_datetime(df.loc[close.index, 'begin'])
                    if hasattr(b_dates, "dt") and hasattr(b_dates.dt, "tz_localize") and b_dates.dt.tz is not None:
                        b_dates = b_dates.dt.tz_localize(None)
                    mask = b_dates < pd.to_datetime("2024-08-20")
                    if mask.any():
                        close = close.copy()
                        close.loc[mask] = (close.loc[mask] / 8.0).round(2)
                price = float(close.iloc[-1])
                if len(close) < 50:
                    return {"ticker": ticker, "SMA_50": float('nan'), "SMA_200": float('nan'), "RSI": float('nan'), "Price": price}
                sma_50 = close.rolling(50).mean().iloc[-1]
                sma_200 = close.rolling(200).mean().iloc[-1] if len(close) >= 200 else float('nan')
                rsi = calculate_rsi(close).iloc[-1]
                return {"ticker": ticker, "SMA_50": sma_50, "SMA_200": sma_200, "RSI": rsi, "Price": price}
        except Exception:
            pass
        return {"ticker": ticker, "SMA_50": float('nan'), "SMA_200": float('nan'), "RSI": float('nan'), "Price": float('nan')}

    with ThreadPoolExecutor(max_workers=20) as ex:
        results = list(ex.map(get_ticker_tech, tickers))
    return pd.DataFrame(results, columns=cols)

@st.cache_data(ttl=600)
def fetch_bond_prices_moex():
    """
    Одним запросом тянет текущие цены и номиналы всех облигаций с MOEX ISS.
    Возвращает dict: {SECID: {'price': float, 'facevalue': float, 'accrued': float}}
    """
    if not _is_moex_iss_reachable():
        return {}
    rates = {"SUR": 1.0, "RUB": 1.0, "USD": 90.0, "EUR": 100.0, "CNY": 12.0}
    try:
        url_rates = "https://iss.moex.com/iss/engines/currency/markets/selt/boards/CETS/securities.json"
        resp_rates = requests.get(url_rates, params={"iss.meta": "off", "iss.only": "marketdata", "marketdata.columns": "SECID,LAST"}, timeout=5).json()
        for row in resp_rates["marketdata"]["data"]:
            if row[0] == "USD000UTSTOM" and row[1]: rates["USD"] = float(row[1])
            elif row[0] == "EUR_RUB__TOM" and row[1]: rates["EUR"] = float(row[1])
            elif row[0] == "CNYRUB_TOM" and row[1]: rates["CNY"] = float(row[1])
    except Exception:
        pass

    result = {}
    boards = [
        ("stock", "bonds", "TQOB"),   # ОФЗ
        ("stock", "bonds", "TQCB"),   # корпоративные в рублях
        ("stock", "bonds", "TQOY"),   # юаневые облигации (CNY)
        ("stock", "bonds", "TQOD"),   # валютные / замещающие облигации (USD/EUR)
    ]
    for engine, market, board in boards:
        try:
            url = (f"https://iss.moex.com/iss/engines/{engine}/markets/{market}"
                   f"/boards/{board}/securities.json")
            params = {
                "iss.meta": "off",
                "iss.only": "securities,marketdata",
                "securities.columns": "SECID,FACEVALUE,ACCRUEDINT,FACEUNIT",
                "marketdata.columns": "SECID,LAST,LCURRENTPRICE",
            }
            resp = requests.get(url, params=params, timeout=10)
            data = resp.json()

            sec_map = {
                row[0]: {"facevalue": float(row[1] or 1000), "accrued": float(row[2] or 0), "currency": row[3] or "RUB"}
                for row in data["securities"]["data"] if row[0]
            }
            for row in data["marketdata"]["data"]:
                secid = row[0]
                if not secid: continue
                price = row[1] or row[2]  # LAST или LCURRENTPRICE
                if price and secid in sec_map:
                    result[secid] = {
                        "price":     float(price),
                        "facevalue": sec_map[secid]["facevalue"],
                        "accrued":   sec_map[secid]["accrued"],
                        "rate":      rates.get(sec_map[secid]["currency"], 1.0)
                    }
        except Exception:
            pass
    return result

def _sentiment_mtime() -> float:
    """Возвращает mtime sentiment.json как ключ для инвалидации кэша."""
    p = Path(os.path.abspath(__file__)).parent / "sentiment.json"
    return p.stat().st_mtime if p.exists() else 0.0

@st.cache_data(ttl=600)
def load_sentiment_data(_cache_buster: float = 0.0):
    paths_to_try = [
        Path(os.path.abspath(__file__)).parent / "sentiment.json",
        Path.cwd() / "sentiment.json",
        Path("/mnt/new_volume/VS_code_base/moex_helper/sentiment.json")
    ]
    
    sentiment_path = None
    for p in paths_to_try:
        if p.exists():
            sentiment_path = p
            break

    if not sentiment_path:
        st.warning(f"⚠️ Файл сентимента sentiment.json не найден. Проверены пути: {[str(p) for p in paths_to_try]}")
        return {}

    try:
        with open(sentiment_path, "r", encoding="utf-8") as f:
            data = json.load(f)
            return data if isinstance(data, dict) else {}
    except Exception as e:
        st.error(f"⚠️ Ошибка чтения sentiment.json: {e}")
        return {}

@st.cache_data(ttl=3600)
def fetch_smartlab_fundamentals(ticker_list):
    """
    Читает фундаментальные данные из fundamentals_cache.csv,
    который обновляется GitHub Actions каждый будний день в 09:00 МСК.
    Прямой парсинг smart-lab.ru здесь не выполняется — это позволяет
    дашборду работать на Streamlit Cloud без проксей и домашнего ПК.
    """
    cache_path = Path(os.path.abspath(__file__)).parent / "fundamentals_cache.csv"

    if not cache_path.exists():
        st.warning(
            "⚠️ Файл fundamentals_cache.csv не найден. "
            "Запустите GitHub Actions вручную: "
            "репозиторий → Actions → Update Fundamentals Cache → Run workflow."
        )
        return pd.DataFrame(columns=["ticker", "P_E", "ROE_%", "Debt_EBITDA", "Rev_Growth_%", "P_BV", "FCF_Yield_%", "Div_RUB"])

    try:
        df = pd.read_csv(cache_path)
    except Exception as e:
        st.error(f"Не удалось прочитать кэш: {e}")
        return pd.DataFrame(columns=["ticker", "P_E", "ROE_%", "Debt_EBITDA", "Rev_Growth_%", "P_BV", "FCF_Yield_%", "Div_RUB"])

    # Для банков нет Debt/EBITDA — подставляем безопасную константу если отсутствует
    if 'Debt_EBITDA' in df.columns:
        bank_mask = df['ticker'].isin(BANK_TICKERS) & df['Debt_EBITDA'].isna()
        df.loc[bank_mask, 'Debt_EBITDA'] = 1.0
        zero_mask = df['ticker'].isin(ZERO_DEBT_TICKERS) & df['Debt_EBITDA'].isna()
        df.loc[zero_mask, 'Debt_EBITDA'] = 0.0

    # Отдаём только те тикеры, которые запросил пользователь
    return df[df['ticker'].isin([t.upper() for t in ticker_list])].reset_index(drop=True)

# -------------------------------------------------------------
# ШЛЮЗЫ ВНЕШНЕЙ АНАЛИТИКИ (Russian Magellan PRO + TankerMap)
# -------------------------------------------------------------
@st.cache_data(ttl=300)
def fetch_magellan_order_flow(period: str = "today") -> dict:
    try:
        from src.magellan_gateway import MagellanGateway
        return MagellanGateway().get_order_flow(period)
    except Exception:
        return {}

@st.cache_data(ttl=1800)
def fetch_magellan_banks_summary() -> dict:
    try:
        from src.magellan_gateway import MagellanGateway
        return MagellanGateway().get_banks_summary()
    except Exception:
        return {}

@st.cache_data(ttl=1800)
def fetch_magellan_bank_details(ticker: str):
    try:
        from src.magellan_gateway import MagellanGateway
        return MagellanGateway().get_bank_details(ticker)
    except Exception:
        return None

@st.cache_data(ttl=900)
def fetch_bonds_stress_radar() -> dict:
    try:
        from src.magellan_gateway import MagellanGateway
        return MagellanGateway().get_bonds_stress_radar()
    except Exception:
        return {}

@st.cache_data(ttl=1800)
def fetch_funds_rebalancing() -> dict:
    try:
        from src.magellan_gateway import MagellanGateway
        return MagellanGateway().get_funds_rebalancing()
    except Exception:
        return {}

@st.cache_data(ttl=3600)
def fetch_ipr_summary() -> dict:
    try:
        from src.magellan_gateway import MagellanGateway
        return MagellanGateway().get_ipr_summary()
    except Exception:
        return {}

@st.cache_data(ttl=900)
def fetch_tankermap_export_stats() -> dict:
    try:
        from src.tankermap_gateway import TankerMapGateway
        return TankerMapGateway().get_russian_export_analytics()
    except Exception as exc:
        st.sidebar.warning(f"Ошибка загрузки TankerMap: {exc}")
        return {}

@st.cache_data(ttl=1800)
def fetch_tankermap_chokepoints() -> dict:
    try:
        from src.tankermap_gateway import TankerMapGateway
        return TankerMapGateway().get_chokepoints_analytics()
    except Exception:
        return {}

@st.cache_data(ttl=1800)
def fetch_tankermap_news() -> list:
    try:
        from src.tankermap_gateway import TankerMapGateway
        return TankerMapGateway().get_maritime_news()
    except Exception:
        return []

# ==========================================
# 3. БИЗНЕС-ЛОГИКА И РАСЧЕТЫ
# ==========================================
HEALTH_SCORE_EXPLANATION = """
**Health Score** — это многофакторный математический рейтинг инвестиционной привлекательности компании на базе принципов **Value & Income / Income Reversion** (консервативное дивидендное ядро, свободный кэш FCF и защита от «турецкого риска» инфляции), дополненный микроструктурой стакана и морской логистикой.

Рейтинг стартует с оценки фундаментальной доходности и динамически масштабируется коэффициентами:

---
### 1. Value & Income и Income Reversion («Рывок доходности»)
- **Устойчивое ядро (`ROE` + `P/E` + `FCF`):** Высокая отдача на капитал при низком долге.
- **Income Reversion (Рывок доходности):** Если компания с низким долгом (`Debt/EBITDA ≤ 1.5x`) уже платит дивиденд и генерирует высокий свободный кэш (`FCF Yield ≥ 12%`) или растёт >12%/год при высоком ROE, временная просадка бумажного `P/E` компенсируется силой FCF.
- **Дисциплина дивидендов («Без дивов — нафиг»):**
  - Нулевые дивиденды вне IT-сектора ➡️ штраф **×0.55** (кроме чистых цикличных компаний на дне цикла: ×0.80).
  - Низкие дивиденды (`< 6%`) без роста/FCF-рывка ➡️ штраф **×0.72**.
  - Выплата дивов в долг (`Payout > 100%` или `FCF < 0`) ➡️ штраф **×0.72**.
  - Устойчивые дивиденды из прибыли/FCF (`≥ 6–18%`) ➡️ премия до **×1.18** (режется вдвое для стагнирующих квазиоблигаций).

---
### 2. Структурный дисконт и Дистресс (Защита от ловушек)
- **Структурный дисконт (`SNGS`, `SNGSP`, `GAZP`, `FEES`, `UPRO`):** Не используется наивный мультипликатор `3.0 / P_BV` и бонус за недоступную миноритариям кубышку. Сургутнефтегаз (ао) учитывается с постоянным корпоративным дисконтом (`×0.45`) и низкой текущей отдачей.
- **Убыточность и отрицательный капитал (`P/E ≤ 0`, `P/BV ≤ 0` вне IT):** Принудительное обнуление скора (`0.0`).
- **Регулируемые сетевые/энергетические компании (`UTILITIES`):** Консервативный коэффициент **×0.85**.

---
### 3. Долговая нагрузка и Критерии банкротства (Solvency)
- `Debt/EBITDA > 3.0` ➡️ отсев / критический риск при жесткой ДКП.
- Истинный отрицательный чистый долг (кроме закрытых кубышек) ➡️ бонус до **×2.0**.
- Токсичные эмитенты (Черный список) ➡️ изоляция в карантин (`0.0`).

---
### 4. 🌊 Микроструктура торгов и Order Flow (Russian Magellan PRO)
- `🟢 Накопление` (**×1.15**), `🔄 Разворот спроса` (**×1.10**), `🔴 Скрытый сброс` (**×0.85**), баланс покупок и крупные пакеты ("Киты" > 30 млн ₽).

---
### 5. 🏦 Банковский сектор по РСБУ (Формы 101/102 ЦБ РФ через Magellan)
- **Реальный ROE LTM**, достаточность капитала **Н1.0** (`≥ 12%` ➡️ ×1.15, `< 9.5%` ➡️ ×0.70), просрочка (`< 3.5%` ➡️ ×1.05, `> 6.0%` ➡️ ×0.88) и динамика прибыли г/г.

---
### 6. 🚢 Морская логистика и Физический экспорт (TankerMap live AIS)
- Загрузка нефтяных терминалов и DWT в море (нефтегаз, `TRNFP`, `NMTP`, `FLOT`, `NVTK`).

---
### 7. Инфляционный радар, Бондовый стресс (TQCB), БПИФ и Макро-часы
- Альтернативная стоимость денег (ключевая ставка ЦБ), защита от сжигания капитала ниже инфляции, доходность корпоративных бондов (`YTM ≥ 50%` ➡️ ×0.45; `YTM ≥ 28%` ➡️ ×0.70), притоки/оттоки БПИФ и секторная ротация.

*Активы с итоговым счетом **ниже 0.85** признаются слабыми (кандидаты на выход). Лидеры **Value & Income / Income Reversion** получают оценку **> 1.3**.*
"""

def build_portfolio_rules(index_level, usd_rate):
    if index_level is None: index_level = 2600
    if usd_rate is None: usd_rate = 80

    # Штанга (Barbell): 80-90% ядро Value & Income + 10-20% валютный/золотой резерв без длинных RUB ОФЗ
    if index_level <= 2200:
        cash_target, bond_target, regime = 0.05, 0.10, "Глубокий дисконт — разворачиваем резерв в акции"
    elif index_level <= 2900:
        cash_target, bond_target, regime = 0.05, 0.15, "Базовый режим Штанги — 80% Value & Income / 20% Щит"
    else:
        cash_target, bond_target, regime = 0.10, 0.20, "Перегрев рынка — копим валютный/золотой резерв"

    bond_currency = "Валютный / Золотой щит + фонд ликвидности (0% длинных RUB ОФЗ — турецкий риск)"
    equity_target = 1 - cash_target - bond_target
    
    return {"cash_target": cash_target, "bond_target": bond_target, "equity_target": equity_target, "regime": regime, "bond_currency": bond_currency}

def build_position_weights(ranked_df, equity_target, max_single=0.15, rest_cap=0.05, n_assets=10):
    if ranked_df.empty:
        return pd.DataFrame(columns=["ticker", "weight"])
    # Берём только топ-N активов по Health_Score
    ranked_df = ranked_df.head(n_assets).copy()
    ranked_df = ranked_df.reset_index(drop=True)
    weights = [max_single if i < 3 else rest_cap for i in range(len(ranked_df))]
    scale = min(1.0, equity_target / sum(weights))
    ranked_df["weight"] = [w * scale for w in weights]
    ranked_df["weight"] = ranked_df["weight"].clip(upper=max_single)
    return ranked_df[["ticker", "Health_Score", "weight", "ROE_%", "P_E", "Debt_EBITDA"]]

# ==========================================
# 4. ИНТЕРФЕЙС И ОТРИСОВКА
# ==========================================
with st.sidebar:
    st.header("Настройки портфеля")
    if "ignore_liquidity" not in st.session_state:
        st.session_state.ignore_liquidity = False
        
    if st.button("Переключить фильтр ликвидности", width="stretch"):
        st.session_state.ignore_liquidity = not st.session_state.ignore_liquidity
        
    ignore_liquidity = st.session_state.ignore_liquidity
    if ignore_liquidity:
        st.warning("Фильтр ликвидности: **ОТКЛЮЧЕН** (Рынок закрыт)")
    else:
        st.success("Фильтр ликвидности: **ВКЛЮЧЕН**")
    moex_universe = fetch_moex_universe(ignore_liquidity=ignore_liquidity)
    moex_tickers = moex_universe["ticker"].tolist()
    if moex_universe.attrs.get("is_fallback"):
        st.caption("⚠️ MOEX ISS временно не отвечает — загружен резервный список тикеров.")
    st.caption(
        f"MOEX TQBR, 1–2 эшелон, оборот ≥ {MIN_DAILY_TURNOVER_RUB // 1_000_000} млн ₽: "
        f"{len(moex_tickers)} тикеров"
    )
    st.header("Мой Портфель")
    izi_cfg = get_izi_config()
    has_izi = bool(
        izi_cfg.get("token")
        if hasattr(izi_cfg, "get")
        else (izi_cfg[1] if isinstance(izi_cfg, (list, tuple)) and len(izi_cfg) > 1 else None)
    )

    source_options = []
    if has_izi:
        source_options.append("⚡ izi-invest (MCP онлайн)")
    source_options.append("📁 Загрузить файл (Excel / CSV / JSON)")
    sample_file_path = Path("data/sample_portfolio.xlsx")
    has_sample = sample_file_path.exists()
    if has_sample:
        source_options.append("🧪 Демо-портфель")

    port_source = st.radio(
        "Источник портфеля:",
        options=source_options,
        index=0 if has_izi else (0 if len(source_options) == 1 else 1),
        label_visibility="collapsed"
    )

    mcp_data = None
    uploaded_file = None
    use_sample = False

    if port_source == "⚡ izi-invest (MCP онлайн)":
        user_ports = get_user_portfolios()
        if user_ports:
            PORTFOLIO_ROLE_TITLES = {
                47933: "💼 Единый рабочий портфель (Альфа + ВТБ)",
                43431: "📈 Основной: Акции (Альфа-Банк)",
                43436: "💵 Валютный щит: Резерв / Облигации (ВТБ)",
                43551: "🔒 Заблокировано: Фонды FinEx (LOCK)",
            }
            port_name_map = {}
            default_idx = 0
            for idx, p in enumerate(user_ports):
                pid = p["id"]
                custom_title = PORTFOLIO_ROLE_TITLES.get(pid)
                if not custom_title:
                    b_title = f" ({p['broker_title']})" if p.get('broker_title') and p['broker_title'] != "Без брокера" else ""
                    custom_title = f"{p['name']}{b_title}"
                port_name_map[pid] = custom_title
                if p.get("merged") or pid == 47933:
                    default_idx = idx

            c_sel, c_ref = st.columns([4, 1])
            with c_sel:
                selected_port_id = st.selectbox(
                    "Активный портфель izi:",
                    options=list(port_name_map.keys()),
                    format_func=lambda pid: port_name_map[pid],
                    index=default_idx,
                    help="Выберите портфель для синхронизации и аудита"
                )
            with c_ref:
                if st.button("🔄", help="Сбросить кэш и обновить данные izi-invest"):
                    st.cache_data.clear()
                    st.rerun()

            st.caption("💡 **Структура капитала:** Альфа (акции) + ВТБ (валютный щит от девальвации) + LOCK (заблокированный FinEx).")

            try:
                with st.spinner(f"Синхронизация {port_name_map.get(selected_port_id, '')} через MCP..."):
                    mcp_data = fetch_izi_mcp_portfolio(selected_port_id)
                if mcp_data and mcp_data.get("from_cache"):
                    st.caption("ℹ️ *Данные загружены из сохранённого кэша (сервер izi-invest ответил с задержкой). Нажмите 🔄 для обновления.*")
            except Exception as e:
                st.error(f"Ошибка загрузки через MCP: {e}")
                mcp_data = None
        else:
            st.warning("Не удалось получить список портфелей из izi-invest. Проверьте токен в .env.")

    elif port_source == "📁 Загрузить файл (Excel / CSV / JSON)":
        uploaded_file = st.file_uploader("Загрузить Портфель (JSON / Excel / CSV)", type=["json", "xlsx", "csv"])

    elif port_source == "🧪 Демо-портфель":
        try:
            with open(sample_file_path, "rb") as sf:
                sample_bytes = sf.read()
            uploaded_file = BytesIO(sample_bytes)
            uploaded_file.name = "sample_portfolio.xlsx"
            uploaded_file.size = len(sample_bytes)
        except Exception:
            uploaded_file = None

    my_portfolio = {}
    my_reserves_invested = 0.0
    my_blocked_invested = 0.0
    cash_rub = 0.0
    _reserves_detail = {}

    FX_RATES = {"USD": 95.0, "EUR": 103.0, "CNY": 13.5, "RUB": 1.0, "RUR": 1.0, "CASH": 1.0}

    if mcp_data is not None:
        my_portfolio = mcp_data.get("my_portfolio_dict", {})
        my_reserves = mcp_data.get("my_reserves_dict", {})
        my_blocked = mcp_data.get("my_blocked_dict", {})
        cash_rub = mcp_data.get("cash_rub", 0.0)
        my_reserves_invested = mcp_data.get("reserves_market_value", 0.0)
        my_blocked_invested = mcp_data.get("blocked_total", 0.0)
        _reserves_detail = {
            sym: {"market": v.get("val", 0.0), "cost": v.get("invested", 0.0), "count": v.get("count", 0.0)}
            for sym, v in my_reserves.items()
        }
        st.session_state["mcp_analysis"] = mcp_data.get("analysis", {})
        st.session_state["mcp_summary"] = mcp_data.get("summary", {})
        st.session_state["mcp_chart"] = mcp_data.get("chart_df", pd.DataFrame())
        st.session_state["mcp_active_portfolio_name"] = mcp_data.get("identifier", "")

    elif uploaded_file is not None:
        if uploaded_file.size > 25 * 1024 * 1024:
            st.error("Размер файла превышает безопасный лимит (25 МБ).")
            uploaded_file = None

    if uploaded_file is not None:
        my_reserves = {}
        my_blocked = {}
        
        if uploaded_file.name.endswith(".json"):
            data = json.load(uploaded_file)
            assets = {a['id']: a['symbol'] for a in data.get('assets', [])}
            
            for t in data.get('trades', []):
                aid = t.get('asset')
                count = t.get('count', 0)
                if aid is None or count == 0: continue
                
                sym = assets.get(aid)
                if not sym: continue
                    
                if sym in ['CASH', 'RUB', 'RUR', 'USD', 'EUR', 'CNY']:
                    rate = FX_RATES.get(sym, 1.0)
                    summa_val = abs(t.get('summa', 0)) * rate
                    if count > 0:
                        cash_rub += summa_val
                    else:
                        cash_rub = max(0.0, cash_rub - summa_val)
                    continue
                    
                if sym in moex_tickers:
                    target_dict = my_portfolio
                elif sym.startswith('FX') or sym in ['RUSE', 'RSHE', 'Unknown']:
                    target_dict = my_blocked
                else:
                    target_dict = my_reserves
                
                if sym not in target_dict:
                    target_dict[sym] = {'count': 0, 'invested': 0.0}
                    
                target_dict[sym]['count'] += count
                if count > 0:
                    target_dict[sym]['invested'] += abs(t.get('summa', 0))
                else:
                    if target_dict[sym]['count'] - count > 0:
                        avg_p = target_dict[sym]['invested'] / (target_dict[sym]['count'] - count)
                        target_dict[sym]['invested'] = max(0.0, target_dict[sym]['invested'] - abs(count) * avg_p)

            for cb in data.get('cash-balances', []):
                for cash_item in cb.get('cash', []):
                    curr = cash_item.get('currency', 'RUB')
                    rate = FX_RATES.get(curr, 1.0)
                    cash_rub += cash_item.get('value', 0) * rate

        elif uploaded_file.name.endswith((".xlsx", ".csv")):
            # ISIN: 12-символьный код вида RU000A..., SU262..., XS... и т.п.
            _isin_re = re.compile(r'^[A-Z]{2}[0-9A-Z]{10}$')

            if uploaded_file.name.endswith(".csv"):
                # encoding='utf-8-sig' срезает BOM (\ufeff) из экспортов Snowball / Excel
                df_upload = pd.read_csv(uploaded_file, encoding='utf-8-sig')
                _trades_parsed = False   # пойдём в generic-блок ниже
            else:
                xl = pd.ExcelFile(uploaded_file)

                # ── Вариант A: Готовый лист "Портфель" (точнее отражает текущие остатки) ──
                if "Портфель" in xl.sheet_names:
                    df_upload = pd.read_excel(xl, sheet_name="Портфель")
                    _trades_parsed = False

                # ── Вариант B: личный журнал сделок (лист «Сделки») ─────────────────
                elif "Сделки" in xl.sheet_names:
                    df_tr = pd.read_excel(xl, sheet_name="Сделки")
                    df_tr.columns = [str(c).strip() for c in df_tr.columns]

                    t_col  = next((c for c in df_tr.columns if c.lower() in ["тикер", "ticker", "symbol"]), None)
                    op_col = next((c for c in df_tr.columns if c.lower() in ["операция", "operation"]), None)
                    ty_col = next((c for c in df_tr.columns if c.lower() == "тип"), None)
                    q_col  = next((c for c in df_tr.columns if c.lower() in ["количество", "qty", "кол-во", "кол."]), None)
                    s_col  = next((c for c in df_tr.columns if c.lower() in ["сумма", "sum", "summa"]), None)
                    d_col  = next((c for c in df_tr.columns if any(k in c.lower() for k in ["дата", "date"])), None)

                    if t_col and op_col and q_col:
                        from src.portfolio_importer import adjust_trade_for_splits
                        net_qty      = {}
                        net_invested = {}
                        net_type     = {}

                        for _, row in df_tr.iterrows():
                            sym = str(row.get(t_col, "")).strip().upper()
                            op  = str(row.get(op_col, "")).strip().lower()
                            typ = str(row.get(ty_col, "")).strip().lower() if ty_col else ""
                            trade_date = pd.to_datetime(row.get(d_col, datetime.now())) if d_col else datetime.now()
                            try:
                                qty = float(row.get(q_col, 0) or 0)
                            except:
                                qty = 0.0
                            try:
                                summa = abs(float(row.get(s_col, 0) or 0)) if s_col else 0.0
                            except:
                                summa = 0.0

                            if not sym or sym in ("NAN", "NONE") or qty == 0:
                                continue
                            if op in ("input", "output", "налог", "купон", "дивиденд"):
                                continue

                            is_buy  = op == "buy" or op.startswith("buy")
                            is_sell = op == "sell" or op.startswith("sell")
                            if not (is_buy or is_sell):
                                continue

                            if sym not in net_qty:
                                net_qty[sym]      = 0.0
                                net_invested[sym] = 0.0
                                net_type[sym]     = typ

                            # qty в журнале SIGNED: buy=+N, sell=-N.
                            # Всегда берём abs() — направление задаёт ветка is_buy/is_sell.
                            qty_abs = abs(qty)
                            unit_price = (summa / qty_abs) if qty_abs > 0 and summa > 0 else 0.0
                            qty_adj, _ = adjust_trade_for_splits(sym, trade_date, qty_abs, unit_price)

                            if is_buy:
                                net_qty[sym]      += qty_adj
                                net_invested[sym] += summa
                            else:  # sell
                                prev = net_qty[sym]
                                if prev > 0:
                                    avg_p = net_invested[sym] / prev
                                    sold_q = min(qty_adj, prev)
                                    net_invested[sym] = max(0.0, net_invested[sym] - sold_q * avg_p)
                                    net_qty[sym] = max(0.0, net_qty[sym] - sold_q)
                                else:
                                    net_qty[sym] = 0.0

                        for sym, qty in net_qty.items():
                            if qty < 0.01:
                                continue
                            invested = max(0.0, net_invested.get(sym, 0.0))
                            typ = net_type.get(sym, "")


                            if sym.startswith("FX") or sym in ["RUSE", "RSHE"]:
                                target_dict = my_blocked
                            elif typ == "bond" or _isin_re.match(sym):
                                target_dict = my_reserves
                            elif typ == "etf":
                                target_dict = my_reserves
                            else:
                                target_dict = my_portfolio

                            if sym not in target_dict:
                                target_dict[sym] = {"count": 0, "invested": 0.0}
                            target_dict[sym]["count"]    += qty
                            target_dict[sym]["invested"] += invested

                        _trades_parsed = True
                        df_upload = pd.DataFrame()  # уже разобрано
                    else:
                        st.warning("Лист 'Сделки' найден, но не содержит нужных колонок (Тикер, Операция, Количество).")
                        df_upload = pd.DataFrame()
                        _trades_parsed = True  # ничего не делаем
                else:
                    # ── Вариант C: первая страница по умолчанию ──────────
                    df_upload = pd.read_excel(uploaded_file)
                    _trades_parsed = False

            # ── Generic flat-таблица (CSV или xlsx без листа «Сделки») ────────────────
            if not _trades_parsed and not df_upload.empty:
                df_upload.columns = [str(c).strip().lower() for c in df_upload.columns]
                ticker_col = next((c for c in [
                    'актив', 'тикер', 'ticker', 'акция', 'инструмент', 'symbol'
                ] if c in df_upload.columns), None)
                count_col = next((c for c in [
                    'кол-во', 'количество', 'лоты', 'позиция', 'штук', 'qty', 'quantity', 'count'
                ] if c in df_upload.columns), None)
                price_col = next((c for c in [
                    'средняя цена', 'цена покупки', 'avg price', 'price', 'цена'
                ] if c in df_upload.columns), None)
                invested_col = next((c for c in [
                    'вложено', 'invested', 'сумма', 'cost'
                ] if c in df_upload.columns), None)
                asset_type_col = next((c for c in ['тип', 'type', 'asset type'] if c in df_upload.columns), None)
                sector_col     = next((c for c in ['сектор', 'sector'] if c in df_upload.columns), None)

                if not ticker_col or not count_col:
                    st.error(
                        f"В таблице не найдены колонки 'Тикер' и 'Количество' (или похожие). "
                        f"Найдены колонки: {list(df_upload.columns)}"
                    )
                else:
                    for _, row in df_upload.iterrows():
                        sym = str(row[ticker_col]).strip().upper()
                        if not sym or sym == 'NAN': continue

                        try:
                            count = float(row[count_col])
                        except:
                            continue
                        if count <= 0: continue

                        invested = 0.0
                        if invested_col:
                            try:
                                invested = float(row[invested_col])
                            except:
                                invested = 0.0
                        if pd.isna(invested) or invested == 0.0:
                            if price_col:
                                try:
                                    invested = count * float(row[price_col])
                                except:
                                    invested = 0.0
                            else:
                                invested = 0.0


                        if sym in ['CASH', 'RUB', 'RUR', 'USD', 'EUR', 'CNY']:
                            cash_rub += invested
                            continue
                        elif sym.startswith('FX') or sym in ['RUSE', 'RSHE']:
                            target_dict = my_blocked
                        elif (
                            _isin_re.match(sym)
                            or (asset_type_col and str(row.get(asset_type_col, '')).strip().lower() in ['bond', 'облигация', 'etf', 'фонд'])
                            or (sector_col and str(row.get(sector_col, '')).strip().lower() == 'облигации')
                        ):
                            target_dict = my_reserves
                        else:
                            target_dict = my_portfolio

                        if sym not in target_dict:
                            target_dict[sym] = {'count': 0, 'invested': 0.0}
                        target_dict[sym]['count']    += count
                        target_dict[sym]['invested'] += invested
                    
        # Фильтруем закрытые позиции
        my_portfolio = {k: v for k, v in my_portfolio.items() if v['count'] > 0.01}
        my_reserves = {k: v for k, v in my_reserves.items() if v['count'] > 0.01}
        my_blocked = {k: v for k, v in my_blocked.items() if v['count'] > 0.01}
        
        # Считаем рыночную стоимость резервов через MOEX ISS (не себестоимость!)
        _bond_prices = fetch_bond_prices_moex()
        reserves_market_value = 0.0
        _reserves_detail = {}  # {ticker: {market, cost, count}}
        for sym, v in my_reserves.items():
            cost = v["invested"]
            qty  = v["count"]
            if sym in _bond_prices:
                bp = _bond_prices[sym]
                market = qty * (bp["price"] / 100 * bp["facevalue"] + bp["accrued"]) * bp["rate"]
            else:
                market = cost  # котировки нет — берём себестоимость
            reserves_market_value += market
            _reserves_detail[sym] = {"market": market, "cost": cost, "count": qty}

        blocked_total = sum(v['invested'] for v in my_blocked.values())

        my_reserves_invested = reserves_market_value + cash_rub
        my_blocked_invested  = blocked_total

    if my_portfolio:
        st.session_state["my_portfolio"] = my_portfolio
        portfolio_tickers_list = list(my_portfolio.keys())
        st.success(f"Загружено {len(portfolio_tickers_list)} акций из портфеля (Альфа-Банк)")
        if my_reserves_invested > 0:
            st.info(f"💵 Валютный щит / Облигации (ВТБ): {my_reserves_invested:,.0f} ₽")
            with st.expander("Детализация резервов (Хедж девальвации)"):
                if cash_rub > 0:
                    st.write(f"Свободный кэш (RUB + CNY): **{cash_rub:,.0f} ₽**")
                for sym, d in _reserves_detail.items():
                    pnl     = d["market"] - d["cost"]
                    pnl_pct = (pnl / d["cost"] * 100) if d["cost"] else 0
                    st.write(
                        f"**{sym}**: рынок {d['market']:,.0f} ₽ │ "
                        f"себест. {d['cost']:,.0f} ₽ │ "
                        f"PnL {pnl:+,.0f} ₽ ({pnl_pct:+.1f}%) │ "
                        f"Позиция: {d['count']}"
                    )
        if my_blocked_invested > 0:
            st.warning(f"🔒 Заблокировано FinEx (из Альфы): {my_blocked_invested:,.0f} ₽")
    else:
        portfolio_tickers_list = PORTFOLIO_TICKERS
        
    st.markdown("---")
    
    with st.expander("🌍 Макроэкономика и Часы", expanded=True):
        macro_phases = [
            "Рефляция (Снижение ставки, спад)",
            "Восстановление (Низкая ставка, рост)",
            "Перегрев (Рост ставки, пик)",
            "Стагфляция (Высокая ставка, спад)"
        ]
        # Ставим Рефляцию по умолчанию, согласно вашему макро-сценарию
        selected_phase = st.selectbox("Текущая фаза экономики:", macro_phases, index=0)
    
    st.markdown("---")
    st.header("Выбор активов")
    valid_defaults = [t for t in portfolio_tickers_list if t in moex_tickers]
    
    if "ms_tickers" not in st.session_state:
        st.session_state["ms_tickers"] = valid_defaults
        st.session_state["prev_valid_defaults"] = valid_defaults
    elif st.session_state.get("prev_valid_defaults") != valid_defaults:
        st.session_state["ms_tickers"] = valid_defaults
        st.session_state["prev_valid_defaults"] = valid_defaults

    def set_all_tickers():
        st.session_state["ms_tickers"] = list(moex_tickers)

    st.button("Все доступные (MOEX)", on_click=set_all_tickers)
    
    selected_tickers = st.multiselect(
        "Тикеры для анализа:",
        options=moex_tickers,
        key="ms_tickers"
    )
    
    with st.expander("⚖️ Риск-менеджмент портфеля", expanded=False):
        capital = st.number_input("Размер капитала, ₽", min_value=100000, value=4200000, step=100000)
        n_assets = st.slider("Число активов в портфеле", min_value=3, max_value=20, value=10, step=1,
                             help="Сколько лучших акций по Health Score войдёт в итоговый портфель.")
        max_single_name = st.slider("Макс. доля одной акции", 0.05, 0.15, 0.12, 0.01)
        rest_cap = st.slider("Макс. доля остальных акций", 0.03, 0.05, 0.05, 0.01)

    with st.expander("⚙️ Настройки отбраковки", expanded=False):
        min_roe_filter = st.slider("Мин. ROE (%)", -50.0, 30.0, 5.0, 1.0, help="Компании с ROE ниже этого значения будут удалены.")
        max_debt_filter = st.slider("Макс. Долг/EBITDA", 0.0, 20.0, 4.0, 0.5, help="Компании с Долг/EBITDA выше этого значения будут удалены.")

    st.markdown("---")
    st.markdown("##### 🏛️ База данных Data Foundry")
    foundry_status = get_foundry_status()
    if foundry_status.get("ok"):
        ver = foundry_status.get("dataset_version", "")
        short_ver = ver.split("-")[-1] if "-" in ver else ver[:8]
        ts_str = foundry_status.get("source_updated_at") or foundry_status.get("published_at", "")
        date_display = "Н/Д"
        if ts_str:
            try:
                from datetime import timezone
                dt = datetime.fromisoformat(ts_str)
                msk_dt = dt.astimezone(timezone(timedelta(hours=3)))
                date_display = msk_dt.strftime("%d.%m.%Y %H:%M МСК")
            except Exception:
                date_display = ts_str[:16]
        schema_badge = " ✅ v1" if foundry_status.get("is_schema_supported") else " ⚠️ schema_mismatch"
        st.caption(
            f"🟢 **MCP Онлайн** | Версия: `{short_ver}`{schema_badge}\n\n"
            f"📅 Обновлено: **{date_display}**"
        )
    else:
        err_msg = foundry_status.get("error", "Сервер недоступен")
        st.caption(f"🔴 **MCP Офлайн**: `{err_msg[:30]}`")

with st.spinner("Считываю сигналы систем..."):
    raw_fundamental_data = fetch_smartlab_fundamentals(selected_tickers)
    eval_tickers = (
        sorted(raw_fundamental_data["ticker"].dropna().astype(str).str.upper().unique().tolist())
        if not raw_fundamental_data.empty else []
    )
    market_context = fetch_market_context()
    tech_data = fetch_technical_indicators(eval_tickers)
    sentiment_data = load_sentiment_data(_cache_buster=_sentiment_mtime())
    magellan_of = fetch_magellan_order_flow("today")
    magellan_banks = fetch_magellan_banks_summary()
    tanker_stats = fetch_tankermap_export_stats()
    magellan_bonds = fetch_bonds_stress_radar()
    magellan_funds = fetch_funds_rebalancing()
    magellan_ipr = fetch_ipr_summary()


index_level = market_context.get("IMOEX")
usd_rate = market_context.get("USD000UTSTOM")
rules = build_portfolio_rules(index_level, usd_rate)

# ==========================================
# 3. ФУНДАМЕНТАЛЬНЫЙ СКОРИНГ И ОТБРАКОВКА
# ==========================================
df_fund = pd.DataFrame()
if not raw_fundamental_data.empty:
    df_fund = raw_fundamental_data[raw_fundamental_data["ticker"].isin([t.upper() for t in selected_tickers])].copy()

    # ВРЕЗКА: Аварийный клапан защиты (теперь берем из сайдбара)
    MIN_ROE = min_roe_filter
    MAX_DEBT_EBITDA = max_debt_filter

    df_fund["ROE_%"] = df_fund["ROE_%"].fillna(0)
    df_fund["Debt_EBITDA"] = df_fund["Debt_EBITDA"].fillna(999)

    is_portfolio = df_fund['ticker'].isin(portfolio_tickers_list)
    is_it = df_fund['ticker'].isin(IT_TICKERS)
    is_toxic = df_fund['ticker'].isin(TOXIC_TICKERS)

    # Для IT-компаний игнорируем фильтр по ROE, так как он может быть искажен
    management_filter = (((df_fund['ROE_%'] >= MIN_ROE) & (df_fund['Debt_EBITDA'] <= MAX_DEBT_EBITDA)) | is_portfolio | is_it) & (~is_toxic)

    dropped_tickers = set(df_fund['ticker']) - set(df_fund[management_filter]['ticker'])
    if dropped_tickers:
        toxic_dropped = set(df_fund[is_toxic]['ticker'])
        if toxic_dropped:
            st.error(f"🛑 Карантин: токсичные или предбанкротные компании заблокированы: {', '.join(toxic_dropped)}")
            dropped_tickers = dropped_tickers - toxic_dropped
        if dropped_tickers:
            st.warning(f"⚠️ Сработала защита: компании с плохим управлением удалены: {', '.join(dropped_tickers)}")
    df_fund = df_fund[management_filter].copy()

if not df_fund.empty:
    # 1. Единое слияние с техническими данными и каскадное разрешение актуальной цены (без дублирующего 101-тикерного live_data)
    df_fund = pd.merge(df_fund, tech_data, on="ticker", how="left")
    for num_col, default_val in [
        ("ROE_%", 0.0),
        ("Debt_EBITDA", 1.0),
        ("Rev_Growth_%", 0.0),
        ("P_BV", 1.0),
        ("Div_RUB", 0.0),
    ]:
        if num_col not in df_fund.columns:
            df_fund[num_col] = default_val
        df_fund[num_col] = pd.to_numeric(df_fund[num_col], errors="coerce").fillna(default_val)

    df_fund["P_E"] = pd.to_numeric(df_fund.get("P_E"), errors="coerce").fillna(10.0)
    df_fund["FCF_Yield_%"] = pd.to_numeric(
        df_fund["FCF_Yield_%"] if "FCF_Yield_%" in df_fund.columns else float("nan"),
        errors="coerce",
    )

    df_fund["Price"] = pd.to_numeric(df_fund.get("Price"), errors="coerce")
    if my_portfolio:
        def _port_fallback_price(t):
            item = my_portfolio.get(t, {})
            p = item.get("price")
            if p is not None and pd.notna(p) and float(p) > 0:
                return float(p)
            cnt = item.get("count", 0) or 0
            val = item.get("val", 0) or 0
            if cnt > 0 and val > 0:
                return float(val) / float(cnt)
            return float("nan")
        df_fund["Price"] = df_fund["Price"].fillna(df_fund["ticker"].map(_port_fallback_price))
    if isinstance(magellan_of, dict) and magellan_of:
        df_fund["Price"] = df_fund["Price"].fillna(
            df_fund["ticker"].map(
                lambda t: float(magellan_of[t]["last_price"])
                if isinstance(magellan_of.get(t), dict) and magellan_of[t].get("last_price")
                else float("nan")
            )
        )
    df_fund["Current_Price"] = df_fund["Price"]
    valid_p = df_fund["Current_Price"].where(df_fund["Current_Price"] > 0)
    df_fund["Div_Yield_%"] = ((df_fund["Div_RUB"] / valid_p) * 100.0).fillna(0.0).round(2)

    # Нормализуем ROE (ограничиваем сверху 40%, чтобы аномалии не ломали веса)
    df_fund["ROE_norm"] = df_fund["ROE_%"].clip(upper=40.0)

    is_it = df_fund["ticker"].isin(IT_TICKERS)
    is_structural = df_fund["ticker"].isin(STRUCTURAL_DISCOUNT_TICKERS)
    is_holding = df_fund["ticker"].isin(HOLDING_TICKERS)
    is_bank = df_fund["ticker"].isin(BANK_TICKERS)
    is_cyclical = df_fund["ticker"].isin(CYCLICAL_TICKERS)
    is_toxic_now = df_fund["ticker"].isin(TOXIC_TICKERS)
    is_utility = df_fund["ticker"].isin(UTILITIES_TICKERS)

    # Для IT-компаний, если ROE ушел в минус из-за бухгалтерского списания капитала, берем норматив 30%
    df_fund.loc[is_it & (df_fund["ROE_norm"] <= 0), "ROE_norm"] = 30.0

    # Income Reversion («рывок доходности» по CrimsonAlter):
    # А) Сильный свободный кэш FCF >= 12% при низком долге и наличии дивиденда (например, ROSN / LKOH / TATN / TRNFP)
    is_rev_fcf = (
        (~is_structural)
        & (~is_toxic_now)
        & (~is_bank)
        & (df_fund["Debt_EBITDA"] <= 1.5)
        & (df_fund["Div_RUB"] > 0)
        & (df_fund["FCF_Yield_%"].fillna(-999.0) >= 12.0)
    )
    # Б) Растущие дивидендные компаундеры (ROE >= 15%, рост >= 12%, див.доходность >= 4%, долг <= 1.5x)
    is_rev_growth = (
        (~is_structural)
        & (~is_toxic_now)
        & (df_fund["Debt_EBITDA"] <= 1.5)
        & (df_fund["Div_Yield_%"] >= 4.0)
        & (df_fund["Rev_Growth_%"] >= 12.0)
        & (df_fund["ROE_%"] >= 15.0)
    )
    is_income_reversion = is_rev_fcf | is_rev_growth

    def _classify_crimson_driver(row):
        t = row["ticker"]
        div_y = row["Div_Yield_%"]
        fcf_y = row["FCF_Yield_%"]
        debt_v = row["Debt_EBITDA"]
        pe_v = row["P_E"]
        pb_v = row["P_BV"]
        roe_v = row["ROE_%"]
        if t in TOXIC_TICKERS or (pe_v <= 0 and pb_v <= 0 and t not in IT_TICKERS):
            return "🔴 Риск / Дистресс"
        if t in STRUCTURAL_DISCOUNT_TICKERS:
            if t == "SNGSP" and div_y >= 9.0:
                return "⚖️ Уставной преф / Дисконт КУ"
            return "🔒 Дисконт КУ / Малые дивы"
        if row["_is_income_reversion"]:
            return "🚀 Income Reversion (Рывок доходности)"
        if t in CYCLICAL_TICKERS and debt_v <= 1.8 and pe_v > 0 and roe_v < 15.0:
            return "⏸️ Дно цикла (Без долга)"
        if t in IT_TICKERS:
            return "📈 Рост бизнеса (IT)"
        if div_y >= 8.0 and (pd.isna(fcf_y) or fcf_y >= 0):
            return "💎 Див-База (Value & Income)"
        if div_y <= 0.0:
            return "🚫 Без дивидендов"
        return "⚖️ Умеренная отдача"

    df_fund["_is_income_reversion"] = is_income_reversion
    df_fund["Драйвер (Value & Income)"] = df_fund.apply(_classify_crimson_driver, axis=1)

    growth_multiplier = 1 + (df_fund["Rev_Growth_%"].clip(lower=-50, upper=100) / 100.0)
    safe_debt = df_fund["Debt_EBITDA"].clip(lower=-0.5)

    # Базовый Health Score
    df_fund["Health_Score"] = (((df_fund["ROE_norm"] / df_fund["P_E"].clip(lower=0.5)) / (1 + safe_debt)) * growth_multiplier).round(2)

    # Компенсация временной просадки P/E / ROE для подтвержденного Income Reversion по живому FCF
    rev_fcf_depressed = is_rev_fcf & ((df_fund["P_E"] > 8.0) | (df_fund["ROE_%"] < 14.0))
    if rev_fcf_depressed.any():
        fcf_power = ((df_fund["FCF_Yield_%"].clip(lower=10.0, upper=22.0) / 10.0) / (1 + df_fund["Debt_EBITDA"].clip(lower=-0.2))) * growth_multiplier
        df_fund.loc[rev_fcf_depressed, "Health_Score"] = (
            df_fund.loc[rev_fcf_depressed, "Health_Score"]
            .combine(fcf_power.loc[rev_fcf_depressed], max)
            .round(2)
        )

    # Классические холдинги (только при положительном капитале и прибыли, без 3/PBV на отрицательный капитал)
    valid_holding = is_holding & (df_fund["P_BV"] > 0) & (df_fund["P_E"] > 0)
    df_fund.loc[valid_holding, "Health_Score"] = (
        ((3.0 / df_fund.loc[valid_holding, "P_BV"].clip(lower=0.25)) / (1 + safe_debt[valid_holding])) * growth_multiplier[valid_holding]
    ).round(2)

    # Структурный дисконт (Сургутнефтегаз, Газпром, сети):
    # НЕ применяем 3/PBV и НЕ даем бонус за недоступную миноритариям кубышку (долг клипится от 0.0)
    if is_structural.any():
        pref_sng = is_structural & (df_fund["ticker"] == "SNGSP")
        other_struct = is_structural & (~pref_sng)
        df_fund.loc[pref_sng, "Health_Score"] = (
            ((df_fund.loc[pref_sng, "ROE_norm"].clip(upper=20.0) / df_fund.loc[pref_sng, "P_E"].clip(lower=5.0))
             / (1 + safe_debt[pref_sng].clip(lower=0.0)))
            * 0.65 * growth_multiplier[pref_sng]
        ).round(2)
        df_fund.loc[other_struct, "Health_Score"] = (
            ((df_fund.loc[other_struct, "ROE_norm"].clip(upper=18.0) / df_fund.loc[other_struct, "P_E"].clip(lower=6.0))
             / (1 + safe_debt[other_struct].clip(lower=0.0)))
            * 0.45 * growth_multiplier[other_struct]
        ).round(2)
    
    # Специфика Банков (Финансовый сектор): их оценивают по связке Капитала (P/BV) и Эффективности (ROE).
    # Обогащение банков реальными данными ЦБ РФ (Форма 101/102 из Magellan)
    is_bank = df_fund['ticker'].isin(BANK_TICKERS)
    for ticker in df_fund[is_bank]['ticker']:
        b_details = fetch_magellan_bank_details(ticker)
        if b_details and b_details.get("roe_ltm") is not None:
            cb_roe = float(b_details["roe_ltm"])
            df_fund.loc[df_fund['ticker'] == ticker, "ROE_%"] = cb_roe
            df_fund.loc[df_fund['ticker'] == ticker, "ROE_norm"] = min(max(cb_roe, 5.0), 35.0)

    df_fund.loc[is_bank, "Health_Score"] = (((df_fund.loc[is_bank, "ROE_norm"] / (df_fund.loc[is_bank, "P_BV"].clip(lower=0.1) * 5.0)) / (1 + safe_debt[is_bank])) * growth_multiplier[is_bank]).round(2)

    # Мультипликаторы банковского сектора по форме 101/102 ЦБ РФ (H1.0, просрочка, чистая прибыль)
    for ticker in df_fund[is_bank]['ticker']:
        b_details = fetch_magellan_bank_details(ticker)
        b_sum = magellan_banks.get(ticker, {}) if isinstance(magellan_banks, dict) else {}
        bank_mult = 1.0
        if b_details:
            # 1. Норматив достаточности капитала H1.0 (норматив ЦБ >= 8.0%)
            if b_details.get("h1_0") is not None:
                h1_0 = float(b_details["h1_0"])
                if h1_0 >= 12.0:
                    bank_mult *= 1.15  # Избыток капитала (высокая дивидендная безопасность)
                elif h1_0 < 9.5:
                    bank_mult *= 0.70  # Дефицит капитала (регуляторный риск / допэмиссия)

            # 2. Качество кредитного портфеля по счетам 101 формы (просрочка)
            if b_details.get("overdue_pct") is not None:
                overdue = float(b_details["overdue_pct"])
                if overdue < 3.5:
                    bank_mult *= 1.05  # Эталонное кредитное качество, минимальные резервы
                elif overdue > 6.0:
                    bank_mult *= 0.88  # Высокая просрочка (давление резервов на чистую прибыль)

        # 3. Динамика прибыли банка YTD г/г по форме 102
        if b_sum and b_sum.get("ytd_growth_pct") is not None:
            ytd_g = float(b_sum["ytd_growth_pct"])
            if ytd_g >= 15.0:
                bank_mult *= 1.05  # Рост прибыли банка
            elif ytd_g <= -15.0:
                bank_mult *= 0.92  # Падение прибыли банка

        df_fund.loc[df_fund['ticker'] == ticker, "Health_Score"] = (
            df_fund.loc[df_fund['ticker'] == ticker, "Health_Score"] * bank_mult
        ).round(2)
    
    # Учет макро-контекста: корректировка нефтяников по текущей цене Urals
    urals_price = market_context.get("URALS")
    if urals_price:
        if urals_price < 60:
            oil_multiplier = 0.8  # Штраф за низкие цены на нефть
        elif urals_price >= 75:
            oil_multiplier = 1.2  # Премия за высокие цены на нефть
        else:
            oil_multiplier = 1.0  # Нейтрально
        is_oil = df_fund['ticker'].isin(OIL_TICKERS)
        df_fund.loc[is_oil, "Health_Score"] = (df_fund.loc[is_oil, "Health_Score"] * oil_multiplier).round(2)

    # Учет физической морской логистики экспорта TankerMap live AIS (для нефтяников и транспорта)
    port_distr = tanker_stats.get("port_distribution", {}) if isinstance(tanker_stats, dict) else {}
    active_terminal_vessels = (
        port_distr.get("Балтика (Urals)", 0) +
        port_distr.get("Черное море (Urals / КТК)", 0) +
        port_distr.get("Дальний Восток (ВСТО / ESPO)", 0)
    )
    crude_dwt = tanker_stats.get("loaded_crude_dwt", 0) if isinstance(tanker_stats, dict) else 0
    total_ru_vessels = tanker_stats.get("total_ru_vessels", 0) if isinstance(tanker_stats, dict) else 0

    # Влияние физического танкерного экспорта на нефтяных мейджоров (ROSN, LKOH, SIBN, TATN, SNGS, BANE)
    is_oil = df_fund['ticker'].isin(OIL_TICKERS)
    if crude_dwt >= 2_000_000 or (total_ru_vessels >= 120 and active_terminal_vessels >= 20):
        # Высокая загрузка морских танкеров и открытые терминалы -> валютная выручка стабильна
        df_fund.loc[is_oil, "Health_Score"] = (df_fund.loc[is_oil, "Health_Score"] * 1.08).round(2)
    elif crude_dwt < 800_000 and total_ru_vessels < 50 and total_ru_vessels > 0:
        # Сжатие танкерного флота / логистический тромб в портах -> штраф к экспортной выручке
        df_fund.loc[is_oil, "Health_Score"] = (df_fund.loc[is_oil, "Health_Score"] * 0.90).round(2)

    # Портовая перевалка и прокачка (TRNFP, NMTP)
    is_port_transport = df_fund['ticker'].isin(['TRNFP', 'NMTP'])
    if active_terminal_vessels >= 25:
        # Высокая загрузка терминалов Новороссийска, Приморска, Козьмино -> премия к тарифам перевалки
        df_fund.loc[is_port_transport, "Health_Score"] = (df_fund.loc[is_port_transport, "Health_Score"] * 1.12).round(2)
    elif active_terminal_vessels < 10 and active_terminal_vessels > 0:
        df_fund.loc[is_port_transport, "Health_Score"] = (df_fund.loc[is_port_transport, "Health_Score"] * 0.90).round(2)

    # Танкерный перевозчик Совкомфлот (FLOT)
    is_flot = df_fund['ticker'] == 'FLOT'
    flot_mult = 1.0
    if total_ru_vessels >= 120:
        flot_mult *= 1.10
    chokepoints = fetch_tankermap_chokepoints()
    suez_info = chokepoints.get("suez", {}) if isinstance(chokepoints, dict) else {}
    suez_trend = float(suez_info.get("trend_pct", 0) or 0)
    if suez_trend < -10:
        # Заторы в Суэце / Красном море удлиняют плечо доставки и разгоняют спотовые ставки фрахта
        flot_mult *= 1.05
    df_fund.loc[is_flot, "Health_Score"] = (df_fund.loc[is_flot, "Health_Score"] * flot_mult).round(2)

    # СПГ-логистика для НОВАТЭК (NVTK)
    is_nvtk = df_fund['ticker'] == 'NVTK'
    loaded_lng = tanker_stats.get("loaded_lng_dwt", 0) if isinstance(tanker_stats, dict) else 0
    arctic_ports = port_distr.get("Арктика (Варандей / СПГ)", 0)
    if loaded_lng >= 80_000 or arctic_ports >= 2:
        df_fund.loc[is_nvtk, "Health_Score"] = (df_fund.loc[is_nvtk, "Health_Score"] * 1.05).round(2)
        
        # Учет макро-контекста: Сталевары
    steel_price = market_context.get("STEEL")
    if steel_price:
        # Цикл стали для US HRC: дно обычно ниже $700, пик выше $1000
        if steel_price < 700:
            steel_multiplier = 0.85 # Штраф: цикл стали на дне
        elif steel_price > 1000:
            steel_multiplier = 1.15 # Премия: пик цикла
        else:
            steel_multiplier = 1.0
        is_steel = df_fund['ticker'].isin(STEEL_TICKERS)
        df_fund.loc[is_steel, "Health_Score"] = (df_fund.loc[is_steel, "Health_Score"] * steel_multiplier).round(2)
        
    # Учет макро-контекста: Золотодобытчики
    gold_price = market_context.get("GOLD")
    if gold_price:
        if gold_price > 3500:
            gold_multiplier = 1.2 # Золото в суперцикле
        elif gold_price < 2500:
            gold_multiplier = 0.8
        else:
            gold_multiplier = 1.0
        is_gold = df_fund['ticker'].isin(GOLD_TICKERS)
        df_fund.loc[is_gold, "Health_Score"] = (df_fund.loc[is_gold, "Health_Score"] * gold_multiplier).round(2)
        
    # Учет свободного денежного потока (FCF Yield) - Cash is King!
    if 'FCF_Yield_%' not in df_fund.columns:
        df_fund['FCF_Yield_%'] = float('nan')
        
    def get_fcf_multiplier(yield_val):
        if pd.isna(yield_val):
            return 1.0  # Для банков и прочих FCF неприменим
        if yield_val < 0:
            return 0.7  # Бумажная прибыль, сжигают живой кэш (штраф -30%)
        elif yield_val > 10.0:
            return 1.2  # Cash is King: генерируют отличный кэш (премия +20%)
        else:
            return 1.0
            
    fcf_multiplier = df_fund['FCF_Yield_%'].apply(get_fcf_multiplier)
    df_fund["Health_Score"] = (df_fund["Health_Score"] * fcf_multiplier).round(2)
        
    # Интеграция Sentiment Analysis (Настроения толпы за последний месяц / 30 дней)
    def get_sentiment_info(ticker):
        t_clean = str(ticker).upper().strip()
        data = sentiment_data.get(t_clean)
        # Если для привилегированной акции нет отдельных данных (SBERP, TATNP, SNGSP), берем обыкновенную
        if not data and t_clean.endswith("P") and len(t_clean) > 4:
            data = sentiment_data.get(t_clean[:-1])
        # Проверяем возможные альтернативные тикеры/алиасы
        if not data:
            alt_ticker = {
                "TCSG": "T", "YNDX": "YDEX", "CIAN": "CNRU",
                "FIVE": "X5", "UGC": "UGLD", "NOVA": "BELU"
            }.get(t_clean)
            if alt_ticker:
                data = sentiment_data.get(alt_ticker)

        if not data:
            return 0.0, False
        posts = data.get("posts_analyzed", 0)
        has_recent = data.get("has_recent_posts", posts > 0)
        if not has_recent or posts == 0:
            return 0.0, False
        return data.get("score", 0.0), True

    def get_sentiment_score(ticker):
        score, _ = get_sentiment_info(ticker)
        return score

    def format_sentiment(ticker):
        score, has_posts = get_sentiment_info(ticker)
        if not has_posts:
            return "⚪ Нет сообщений за месяц"
        if score > 0.1:
            return f"🟢 +{score:.2f}"
        elif score < -0.1:
            return f"🔴 {score:.2f}"
        else:
            return f"⚪ {score:.2f}"

    df_fund['Сентимент_Балл'] = df_fund['ticker'].apply(get_sentiment_score)
    df_fund['Сентимент'] = df_fund['ticker'].apply(format_sentiment)
    
    # Прямой подход: позитивный сентимент дает бонус (до +5%), негативный - штраф (до -5%)
    sentiment_multiplier = 1 + (df_fund['Сентимент_Балл'] * 0.05)
    df_fund["Health_Score"] = (df_fund["Health_Score"] * sentiment_multiplier).round(2)

    # Учет Order Flow (микроструктура рынка из Russian Magellan PRO)
    def get_order_flow_multiplier(ticker):
        of_info = magellan_of.get(ticker, {}) if isinstance(magellan_of, dict) else {}
        reading_key = of_info.get("reading_key")
        buy_ratio = of_info.get("buy_ratio", 50.0)
        mult = 1.0
        if reading_key == "accum":
            mult = 1.15  # Накопление / Абсорбция крупными игроками
        elif reading_key == "rev":
            mult = 1.10  # Разворот спроса
        elif reading_key == "distr":
            mult = 0.85  # Скрытое распределение (продажа в стакан)
        elif buy_ratio >= 65.0:
            mult = 1.08  # Преобладание агрессивных покупок
        elif buy_ratio <= 35.0:
            mult = 0.92  # Преобладание агрессивных продаж

        # Институциональные крупные пакеты ("киты" / Big Volume)
        big_bv = of_info.get("big_bv", 0.0)
        big_sv = of_info.get("big_sv", 0.0)
        big_total = big_bv + big_sv
        if big_total >= 30_000_000:  # Объем крупных пакетов более 30 млн ₽
            big_buy_pct = (big_bv / big_total) * 100
            if big_buy_pct >= 65.0:
                mult *= 1.05  # Крупные участники скупают объем
            elif big_buy_pct <= 35.0:
                mult *= 0.95  # Крупные участники сливают объем
        return round(mult, 3)

    def get_of_badge(ticker):
        of_info = magellan_of.get(ticker, {}) if isinstance(magellan_of, dict) else {}
        label = of_info.get("reading_label")
        delta_mln = of_info.get("delta", 0.0) / 1_000_000.0
        if label and label != "—":
            return f"{label} ({delta_mln:+.1f}M ₽)"
        elif delta_mln != 0:
            return f"Δ {delta_mln:+.1f}M ₽"
        return "—"

    df_fund['Поток (OrderFlow)'] = df_fund['ticker'].apply(get_of_badge)
    df_fund['OF_Multiplier'] = df_fund['ticker'].apply(get_order_flow_multiplier)
    df_fund["Health_Score"] = (df_fund["Health_Score"] * df_fund['OF_Multiplier']).round(2)

    # Учет рынка долга и стресса корпоративных облигаций (MOEX TQCB + Magellan)
    def get_bond_health_multiplier(ticker):
        b_info = magellan_bonds.get(ticker, {}) if isinstance(magellan_bonds, dict) else {}
        return b_info.get("health_mult", 1.0)

    def get_bond_badge(ticker):
        b_info = magellan_bonds.get(ticker, {}) if isinstance(magellan_bonds, dict) else {}
        if not b_info:
            return "—"
        max_y = b_info.get("max_ytm")
        level = b_info.get("risk_level")
        if level == "CRITICAL":
            return f"🚨 {max_y:.1f}%"
        elif level == "HIGH":
            return f"⚠️ {max_y:.1f}%"
        elif level == "MEDIUM":
            return f"🟡 {max_y:.1f}%"
        return f"🟢 {max_y:.1f}%"

    df_fund['Бонды YTM'] = df_fund['ticker'].apply(get_bond_badge)
    df_fund['Bond_Multiplier'] = df_fund['ticker'].apply(get_bond_health_multiplier)
    df_fund["Health_Score"] = (df_fund["Health_Score"] * df_fund['Bond_Multiplier']).round(2)

    # Учет институциональной поддержки БПИФ
    def get_fund_flow_multiplier(ticker):
        f_info = magellan_funds.get(ticker, {}) if isinstance(magellan_funds, dict) else {}
        return f_info.get("health_mult", 1.0)

    def get_fund_flow_badge(ticker):
        f_info = magellan_funds.get(ticker, {}) if isinstance(magellan_funds, dict) else {}
        if not f_info:
            return "—"
        w = f_info.get("net_weight_change", 0.0)
        cnt = f_info.get("funds_count", 0)
        if w >= 0.5:
            return f"🟢 +{w:.1f}% ({cnt} ф.)"
        elif w <= -0.5:
            return f"🔴 {w:.1f}% ({cnt} ф.)"
        return f"⚪ {w:+.1f}% ({cnt} ф.)"

    df_fund['БПИФ поток'] = df_fund['ticker'].apply(get_fund_flow_badge)
    df_fund['Fund_Multiplier'] = df_fund['ticker'].apply(get_fund_flow_multiplier)
    df_fund["Health_Score"] = (df_fund["Health_Score"] * df_fund['Fund_Multiplier']).round(2)
    
    # Интеграция Безрисковой Ставки (Key Rate / Cost of Money)
    key_rate_val = market_context.get("KEY_RATE", 16.0)
    
    def apply_rfr_penalty(row):
        score = row['Health_Score']
        ticker = row['ticker']
        div_y = row.get('Div_Yield_%', 0.0)
        fcf_y = row.get('FCF_Yield_%', float('nan'))
        
        # IT-сектор: растут быстрее ставки, оцениваются по мультипликаторам
        if ticker in IT_TICKERS:
            return score
        # Классические холдинги: E/P искажён переоценкой дочек
        if ticker in HOLDING_TICKERS:
            return score
        # Структурный дисконт (SNGS, GAZP и др.): не освобождаются от проверки, если дивы < 10%
        if ticker in STRUCTURAL_DISCOUNT_TICKERS:
            return score if div_y >= 10.0 else round(score * 0.70, 2)
        # Income Reversion (например, ROSN с FCF 19.2%): живой FCF уже выше ставки
        if ticker in OIL_TICKERS and pd.notna(fcf_y) and fcf_y >= 12.0 and row.get('Debt_EBITDA', 99) <= 1.5 and div_y > 0:
            return score
        
        # Цикличные компании (Металлурги, Майнеры): прощаем им низкий E/P на дне цикла, смотрим на ROE
        if ticker in CYCLICAL_TICKERS:
            if row['ROE_norm'] < key_rate_val:
                return round(score * 0.7, 2)
            return score
        
        # Банки: жестко проверяем ROE против ставки
        if ticker in BANK_TICKERS:
            if row['ROE_norm'] < key_rate_val:
                return round(score * 0.7, 2)
            return score
            
        # Обычные компании: проверяем и ROE, и Earnings Yield (E/P)
        earnings_yield = (100 / row['P_E']) if pd.notna(row['P_E']) and row['P_E'] > 0 else 0
        
        if row['ROE_norm'] < key_rate_val or earnings_yield < key_rate_val:
            score = score * 0.7
            
        return round(score, 2)
        
    df_fund["Health_Score"] = df_fund.apply(apply_rfr_penalty, axis=1)
    
    # Единая дисциплина дивидендов Value & Income ("Если дивов нет или они маленькие — нафиг")
    def apply_div_multiplier(row):
        score = row['Health_Score']
        ticker = row['ticker']
        div = row['Div_Yield_%']
        pe = row['P_E']
        fcf = row.get('FCF_Yield_%', float('nan'))
        growth = row.get('Rev_Growth_%', float('nan'))
        is_rev = bool(row.get('_is_income_reversion', False))
        
        # Регулируемые сетевые/энерго компании имеют понижающий коэффициент из-за инвестпрограмм и тарифов
        if ticker in UTILITIES_TICKERS:
            score *= 0.85

        payout_ratio = 0.0
        if pd.notna(div) and div > 0 and pd.notna(pe) and pe > 0:
            payout_ratio = (div * pe) / 100.0
        
        if pd.isna(div) or div <= 0:
            if ticker in IT_TICKERS:
                return round(score, 2)
            if ticker in CYCLICAL_TICKERS and row.get('Debt_EBITDA', 99) <= 1.5:
                return round(score * 0.80, 2)
            return round(score * 0.55, 2)  # Жесткий штраф Value & Income за 0% дивидендов

        if div < 6.0:
            # Прощаем низкий текущий див ТОЛЬКО при доказанном Income Reversion (рост или мощный FCF)
            return round(score * (1.05 if is_rev else 0.72), 2)
            
        # Проедание капитала / выплата дивов в долг
        if payout_ratio > 1.0 or (div >= 10.0 and pd.notna(fcf) and fcf < 0):
            return round(score * 0.72, 2)
            
        # Стагнирующая квазиоблигация vs растущая дивидендная база
        if div > 10.0 and (pd.isna(growth) or growth < 5.0):
            return round(score * (1.0 + (min(div, 18.0) / 200.0)), 2)
            
        return round(score * (1.0 + (min(div, 18.0) / 100.0)), 2)
        
    df_fund["Health_Score"] = df_fund.apply(apply_div_multiplier, axis=1)
    
    # Защита от сжигания капитала (Инфляционный радар / «турецкий риск» инфляции)
    inflation_real_val = market_context.get("INFLATION_REAL", 12.0)
    def apply_inflation_penalty(row):
        score = row['Health_Score']
        roe = row['ROE_norm']
        div = row['Div_Yield_%']
        fcf = row.get('FCF_Yield_%', float('nan'))
        growth = row.get('Rev_Growth_%', 0)
        if pd.isna(growth):
            growth = 0.0
        
        # Для Income Reversion на базе живого FCF учитываем фактическую отдачу кэша
        eff_return = max(roe, float(fcf)) if (row.get('_is_income_reversion') and pd.notna(fcf)) else roe
        is_destroyer = False
        if eff_return < inflation_real_val:
            score *= 0.7
            
        if pd.notna(div) and div > 0:
            if div < inflation_real_val and growth < inflation_real_val and not (row.get('_is_income_reversion') and pd.notna(fcf) and fcf >= inflation_real_val):
                score *= 0.6
                is_destroyer = True
                
        return pd.Series([round(score, 2), is_destroyer])
        
    df_fund[['Health_Score', 'Is_Destroyer']] = df_fund.apply(apply_inflation_penalty, axis=1)
    
    # 🕰️ ИНВЕСТИЦИОННЫЕ ЧАСЫ (Секторная ротация)
    def apply_macro_cycle(row):
        score = row['Health_Score']
        ticker = row['ticker']
        
        if selected_phase.startswith("Рефляция"):
            if ticker in TELECOM_TICKERS or ticker in CONSUMER_TICKERS or ticker in UTILITIES_TICKERS:
                score *= 1.15 # Защитные активы и квазиоблигации
            elif ticker in OIL_TICKERS or ticker in STEEL_TICKERS:
                score *= 0.90 # Сырье под давлением
        elif selected_phase.startswith("Восстановление"):
            if ticker in IT_TICKERS or ticker in BANK_TICKERS:
                score *= 1.20 # Эпицентр роста
            elif ticker in CONSUMER_TICKERS:
                score *= 1.10
        elif selected_phase.startswith("Перегрев"):
            if ticker in OIL_TICKERS or ticker in STEEL_TICKERS:
                score *= 1.20 # Сырьевой суперцикл
            elif ticker in IT_TICKERS:
                score *= 0.85 # Конец цикла роста
        elif selected_phase.startswith("Стагфляция"):
            if ticker in GOLD_TICKERS:
                score *= 1.20 # Спасение в золоте
            elif ticker in IT_TICKERS or ticker in BANK_TICKERS:
                score *= 0.80 # Обвал кредитования и оценки
                
        return round(score, 2)
        
    df_fund["Health_Score"] = df_fund.apply(apply_macro_cycle, axis=1)
    
    def apply_tech_multiplier(row):
        score = row['Health_Score']
        price = row['Price']
        sma50 = row['SMA_50']
        sma200 = row['SMA_200']
        rsi = row['RSI']
        
        if pd.isna(price) or pd.isna(sma50):
            return score, "Н/Д"
            
        trend_label = "Боковик"
        tech_mult = 1.0
        
        if pd.notna(sma200):
            if price < sma50 and price < sma200:
                tech_mult = 0.7
                trend_label = "📉 Даунтренд"
            elif price > sma50 and price < sma200:
                tech_mult = 1.2
                trend_label = "🚀 Разворот"
            elif price > sma50 and price > sma200:
                tech_mult = 1.1
                trend_label = "📈 Аптренд"
            elif price < sma50 and price > sma200:
                tech_mult = 0.9
                trend_label = "⚠️ Коррекция"
        else:
            if price < sma50:
                tech_mult = 0.8
                trend_label = "📉 Даунтренд"
            elif price > sma50:
                tech_mult = 1.1
                trend_label = "📈 Аптренд"
                
        if pd.notna(rsi) and rsi > 75:
            tech_mult *= 0.8 # Штраф за сильную перекупленность
            
        is_destroyer = row.get('Is_Destroyer', False)
        if is_destroyer:
            trend_label = "🔥 Сжигатель"
            
        return round(score * tech_mult, 2), trend_label
        
    df_fund[['Health_Score', 'Тренд']] = df_fund.apply(lambda row: pd.Series(apply_tech_multiplier(row)), axis=1)

    # Финальное обнуление убыточных компаний (P/E <= 0), отрицательного капитала вне IT/Потребсектора (AFKS) и карантина
    neg_equity_loss = (
        (df_fund["P_E"] <= 0)
        & (df_fund["P_BV"] <= 0)
        & (~df_fund["ticker"].isin(IT_TICKERS + CONSUMER_TICKERS))
    )
    loss_or_toxic = (df_fund["P_E"] <= 0) | neg_equity_loss | df_fund["ticker"].isin(TOXIC_TICKERS)
    df_fund.loc[loss_or_toxic, "Health_Score"] = 0.0
    df_fund["Health_Score"] = df_fund["Health_Score"].clip(lower=0.0).round(2)

    df_ranked = df_fund.sort_values(by=["Health_Score"], ascending=False)
    
    # Делаем RSI человекочитаемым
    def format_rsi(rsi_val):
        if pd.isna(rsi_val): return "Н/Д"
        if rsi_val >= 70: return f"{rsi_val:.1f} (🔥 Перегрев)"
        if rsi_val <= 30: return f"{rsi_val:.1f} (❄️ Перепродан)"
        return f"{rsi_val:.1f} (Норма)"
        
    df_ranked['RSI'] = df_ranked['RSI'].apply(format_rsi)
else:
    df_ranked = pd.DataFrame()


if df_ranked.empty:
    st.error("Аварийная остановка: Ни один актив не прошел проверку качества.")
    st.info("Для анализа фундаментальных показателей выберите тикеры в sidebar.")
else:
    # Обогащение фундаментальной оценкой "Чёрная Линия" (Black Line / Fair Value)
    key_rate_for_bl = float(market_context.get("KEY_RATE", 16.0)) if isinstance(market_context, dict) and market_context.get("KEY_RATE") else 16.0
    def calc_bl_metrics(row):
        raw_p = row.get('Price', 0.0)
        p = float(raw_p) if pd.notna(raw_p) and math.isfinite(float(raw_p)) else 0.0
        res = calculate_black_line_valuation(
            ticker=row['ticker'],
            price=p,
            pe=row.get('P_E'),
            pb=row.get('P_BV'),
            roe=row.get('ROE_%'),
            debt_ebitda=row.get('Debt_EBITDA'),
            rev_growth=row.get('Rev_Growth_%'),
            div_rub=row.get('Div_RUB'),
            key_rate=key_rate_for_bl,
            use_mcp=False,
            fcf_yield=row.get('FCF_Yield_%'),
        )
        return pd.Series([res['fair_price'], res['upside_pct']])

    df_ranked[['Чёрная Линия (₽)', 'Margin of Safety (%)']] = df_ranked.apply(calc_bl_metrics, axis=1)

    # Обогащение данными портфеля инвестора
    if my_portfolio:
        def get_port_count(ticker): return my_portfolio.get(ticker, {}).get('count', 0)
        def get_port_invested(ticker): return my_portfolio.get(ticker, {}).get('invested', 0)
        
        df_ranked['Лоты'] = pd.to_numeric(df_ranked['ticker'].apply(get_port_count), errors='coerce').fillna(0.0)
        df_ranked['Вложено'] = pd.to_numeric(df_ranked['ticker'].apply(get_port_invested), errors='coerce').fillna(0.0)
        price_num = pd.to_numeric(df_ranked['Price'], errors='coerce').fillna(0.0)
        df_ranked['Текущая Стоимость'] = (df_ranked['Лоты'] * price_num).fillna(0.0)
        missing_val_mask = (df_ranked['Лоты'] > 0) & (df_ranked['Текущая Стоимость'] <= 0)
        if missing_val_mask.any():
            df_ranked.loc[missing_val_mask, 'Текущая Стоимость'] = df_ranked.loc[missing_val_mask, 'ticker'].map(
                lambda t: float(my_portfolio.get(t, {}).get('val', 0.0) or my_portfolio.get(t, {}).get('invested', 0.0) or 0.0)
            ).fillna(0.0)

        port_mask = df_ranked['Лоты'] > 0
        total_val = float(df_ranked.loc[port_mask, 'Текущая Стоимость'].sum())
        total_inv = float(df_ranked.loc[port_mask, 'Вложено'].sum())
        pnl_rub = total_val - total_inv
        pnl_pct = (pnl_rub / total_inv * 100) if total_inv > 0 else 0.0
        port_health = float((df_ranked.loc[port_mask, 'Health_Score'] * df_ranked.loc[port_mask, 'Текущая Стоимость']).sum() / total_val) if total_val > 0 else 0.0

        df_ranked['Доля в портфеле (%)'] = (df_ranked['Текущая Стоимость'] / total_val * 100).fillna(0).round(1) if total_val > 0 else 0.0
        df_ranked['PnL (%)'] = ((df_ranked['Текущая Стоимость'] - df_ranked['Вложено']) / df_ranked['Вложено'].replace(0, 1) * 100).fillna(0).round(1)

        df_port = df_ranked[port_mask].copy()
    else:
        total_val = 0.0
        total_inv = 0.0
        pnl_rub = 0.0
        pnl_pct = 0.0
        port_health = 0.0
        df_port = pd.DataFrame()
        df_ranked['Лоты'] = 0
        df_ranked['Вложено'] = 0.0
        df_ranked['Текущая Стоимость'] = 0.0
        df_ranked['Доля в портфеле (%)'] = 0.0
        df_ranked['PnL (%)'] = 0.0

    # Расчет целевых долей ребалансировки
    position_df = build_position_weights(
        df_ranked, rules["equity_target"],
        max_single=max_single_name, rest_cap=rest_cap, n_assets=n_assets
    )
    position_df["target_value_rub"] = (
        pd.to_numeric(position_df["weight"], errors="coerce").fillna(0.0) * float(capital or 0.0)
    ).fillna(0.0).round(0).astype(int)
    target_weights_map = dict(zip(position_df["ticker"], position_df["weight"]))
    df_ranked["Идеальная доля (%)"] = df_ranked["ticker"].map(lambda t: round(target_weights_map.get(t, 0.0) * 100, 1))

    # Классификация бумаг для принятия решений (Что продать / Что купить / Рокировки)
    target_max_pct = max_single_name * 100.0

    if not df_port.empty:
        toxic_mask = df_port['ticker'].isin(TOXIC_TICKERS)
        debt_crisis_mask = (df_port['Debt_EBITDA'] > 3.0) & (
            (df_port['ROE_%'] < 8.0) | ((df_port['P_E'] <= 0) & (df_port['P_BV'] <= 0))
        )
        urgent_sells_df = df_port[toxic_mask | debt_crisis_mask].copy()

        # Переоценка по Чёрной Линии (рыночная цена существенно выше внутренней стоимости)
        overvalued_mask = (df_port['Margin of Safety (%)'] <= -25.0) & (~df_port['ticker'].isin(urgent_sells_df['ticker']))
        overvalued_bl_df = df_port[overvalued_mask].copy()

        # Структурно дисконтные бумаги (SNGS, GAZP) не оправдываем как "дно цикла"
        cyclical_mask = df_port['ticker'].isin(CYCLICAL_TICKERS + CONSUMER_TICKERS + OIL_TICKERS) & (
            ~df_port['ticker'].isin(STRUCTURAL_DISCOUNT_TICKERS)
        )
        safe_debt_mask = (df_port['Debt_EBITDA'] <= 1.8) | (df_port['Debt_EBITDA'] < 0)
        hold_cycle_df = df_port[
            (~df_port['ticker'].isin(urgent_sells_df['ticker'])) & 
            (~df_port['ticker'].isin(overvalued_bl_df['ticker'])) &
            cyclical_mask & 
            safe_debt_mask & 
            (df_port['Health_Score'] < 1.25)
        ].copy()

        overweight_df = df_port[
            (~df_port['ticker'].isin(urgent_sells_df['ticker'])) &
            (~df_port['ticker'].isin(overvalued_bl_df['ticker'])) &
            (~df_port['ticker'].isin(hold_cycle_df['ticker'])) &
            (df_port['Доля в портфеле (%)'] > target_max_pct + 1.0)
        ].copy()

        weak_stocks_df = df_port[
            (~df_port['ticker'].isin(urgent_sells_df['ticker'])) &
            (~df_port['ticker'].isin(overvalued_bl_df['ticker'])) &
            (~df_port['ticker'].isin(hold_cycle_df['ticker'])) &
            (~df_port['ticker'].isin(overweight_df['ticker'])) &
            (df_port['Health_Score'] < 0.85)
        ].copy()
    else:
        urgent_sells_df = pd.DataFrame()
        overvalued_bl_df = pd.DataFrame()
        hold_cycle_df = pd.DataFrame()
        overweight_df = pd.DataFrame()
        weak_stocks_df = pd.DataFrame()

    # Топ покупок рынка (Value & Income + Income Reversion + Margin of Safety по Чёрной Линии)
    is_rev_mask = (
        df_ranked['_is_income_reversion']
        if '_is_income_reversion' in df_ranked.columns
        else pd.Series(False, index=df_ranked.index)
    )
    market_buys = df_ranked[
        (~df_ranked['ticker'].isin(TOXIC_TICKERS)) &
        (~df_ranked['ticker'].isin(['SNGS', 'GAZP', 'FEES', 'UPRO'])) &
        (df_ranked['Health_Score'] >= 1.15) &
        (df_ranked['Debt_EBITDA'] <= 1.8) &
        ((df_ranked['ROE_%'] >= 14.0) | is_rev_mask) &
        (df_ranked['Margin of Safety (%)'] >= 0.0)
    ].copy()

    if not df_port.empty:
        port_tickers_set = set(df_port['ticker'])
        top_new_buys = market_buys[~market_buys['ticker'].isin(port_tickers_set)].head(4)
        top_add_buys = market_buys[market_buys['ticker'].isin(port_tickers_set) & (market_buys['Доля в портфеле (%)'] < market_buys['Идеальная доля (%)'])].head(3)
        top_buys_df = pd.concat([top_new_buys, top_add_buys]).drop_duplicates(subset=['ticker']).head(4)
    else:
        top_buys_df = market_buys.head(4)

    # Генерация сценариев рокировки (Smart Swaps) без дублирования и с защитой от NaN
    def _pick_buy_candidate(buys_df, exclude_ticker):
        if buys_df is None or buys_df.empty:
            return None
        diff = buys_df[buys_df['ticker'] != exclude_ticker]
        return diff.iloc[0] if not diff.empty else None

    def _safe_float(val, default=0.0):
        try:
            f = float(val)
            return f if math.isfinite(f) else default
        except (TypeError, ValueError):
            return default

    def _append_smart_swap(swaps_list, buys_df, sell_ticker, sell_val, badge, sell_reason, buy_driver, effect):
        s_val = _safe_float(sell_val, 0.0)
        if s_val <= 0:
            return
        buy_cand = _pick_buy_candidate(buys_df, sell_ticker)
        if buy_cand is None:
            return
        b_t = buy_cand['ticker']
        b_p = _safe_float(buy_cand.get('Price'), 0.0)
        if b_p <= 0:
            return
        lot_size = 10 if b_t in ['SBER', 'SBERP', 'VTBR'] else 1
        shares_cnt = int(s_val // b_p)
        lots_cnt = shares_cnt // lot_size if lot_size > 0 else shares_cnt
        b_val = lots_cnt * lot_size * b_p
        rem_cash = max(0.0, s_val - b_val)

        swaps_list.append({
            "badge": badge,
            "sell_ticker": sell_ticker,
            "sell_val": s_val,
            "sell_reason": sell_reason,
            "buy_ticker": b_t,
            "buy_lots": lots_cnt,
            "buy_val": b_val,
            "rem_cash": rem_cash,
            "buy_driver": buy_driver,
            "effect": effect,
        })

    smart_swaps = []
    if not urgent_sells_df.empty and not top_buys_df.empty:
        for _, sell_row in urgent_sells_df.head(2).iterrows():
            s_t = sell_row['ticker']
            buy_cand = _pick_buy_candidate(top_buys_df, s_t)
            if buy_cand is None:
                continue
            roe_diff = _safe_float(buy_cand.get('ROE_%')) - _safe_float(sell_row.get('ROE_%'))
            debt_diff = _safe_float(sell_row.get('Debt_EBITDA')) - _safe_float(buy_cand.get('Debt_EBITDA'))
            _append_smart_swap(
                smart_swaps, top_buys_df, s_t, sell_row.get('Текущая Стоимость'),
                badge="🔴 Срочный выход из токсичного долга",
                sell_reason=f"Долг/EBITDA {_safe_float(sell_row.get('Debt_EBITDA')):.1f}x при ставке {key_rate_for_bl:.1f}% сжигает прибыль",
                buy_driver=f"ROE {_safe_float(buy_cand.get('ROE_%')):.1f}%, P/E {_safe_float(buy_cand.get('P_E')):.1f}, Health Score {_safe_float(buy_cand.get('Health_Score')):.2f}x",
                effect=f"Рост отдачи на капитал: ROE {roe_diff:+.1f}%, снижение долговой нагрузки на {debt_diff:.1f}x",
            )

    if not overweight_df.empty and not top_buys_df.empty:
        for _, ow_row in overweight_df.head(1).iterrows():
            o_t = ow_row['ticker']
            excess_pct = max(0.0, _safe_float(ow_row.get('Доля в портфеле (%)')) - target_max_pct)
            excess_rub = total_val * (excess_pct / 100.0)
            buy_cand = _pick_buy_candidate(top_buys_df, o_t)
            if excess_rub >= 10_000 and buy_cand is not None:
                _append_smart_swap(
                    smart_swaps, top_buys_df, o_t, excess_rub,
                    badge="🟠 Ребалансировка (Снятие перевеса)",
                    sell_reason=f"Доля {_safe_float(ow_row.get('Доля в портфеле (%)')):.1f}% превышает лимит {target_max_pct:.0f}%",
                    buy_driver=f"ROE {_safe_float(buy_cand.get('ROE_%')):.1f}%, Health Score {_safe_float(buy_cand.get('Health_Score')):.2f}x",
                    effect="Снижение концентрации риска в одной бумаге, покупка фундаментального лидера",
                )

    if not weak_stocks_df.empty and not top_buys_df.empty and len(smart_swaps) < 3:
        for _, w_row in weak_stocks_df.head(1).iterrows():
            w_t = w_row['ticker']
            buy_cand = _pick_buy_candidate(top_buys_df, w_t)
            if buy_cand is not None:
                _append_smart_swap(
                    smart_swaps, top_buys_df, w_t, w_row.get('Текущая Стоимость'),
                    badge="⚠️ Замена отстающей позиции",
                    sell_reason=f"Health Score {_safe_float(w_row.get('Health_Score')):.2f}x уступает среднерыночному",
                    buy_driver=f"ROE {_safe_float(buy_cand.get('ROE_%')):.1f}%, Health Score {_safe_float(buy_cand.get('Health_Score')):.2f}x",
                    effect="Перекладка в актив с восходящей динамикой прибыли",
                )

    if not overvalued_bl_df.empty and not top_buys_df.empty and len(smart_swaps) < 4:
        for _, ov_row in overvalued_bl_df.head(1).iterrows():
            ov_t = ov_row['ticker']
            buy_cand = _pick_buy_candidate(top_buys_df, ov_t)
            if buy_cand is not None:
                _append_smart_swap(
                    smart_swaps, top_buys_df, ov_t, ov_row.get('Текущая Стоимость'),
                    badge="🔄 Рокировка: выход из переоценки по Чёрной Линии",
                    sell_reason=f"Биржевая цена {_safe_float(ov_row.get('Price')):.1f} ₽ существенно выше Чёрной Линии {_safe_float(ov_row.get('Чёрная Линия (₽)')):.1f} ₽ ({_safe_float(ov_row.get('Margin of Safety (%)')):+.1f}%)",
                    buy_driver=f"Чёрная Линия {_safe_float(buy_cand.get('Чёрная Линия (₽)')):.1f} ₽ (Запас {_safe_float(buy_cand.get('Margin of Safety (%)')):+.1f}%), Health Score {_safe_float(buy_cand.get('Health_Score')):.2f}x",
                    effect="Фиксация переоцененного актива и перекладка в фундаментальный дисконт с запасом прочности",
                )

    # Назначение статуса действия для таблицы Светофор
    def assign_action_badge(row):
        t = row['ticker']
        hs = row.get('Health_Score', 1.0)
        debt = row.get('Debt_EBITDA', 999.0)
        roe = row.get('ROE_%', 0.0)
        pe = row.get('P_E', 0.0)
        pb = row.get('P_BV', 0.0)
        is_rev = bool(row.get('_is_income_reversion', False))
        in_p = row.get('Лоты', 0) > 0
        share = row.get('Доля в портфеле (%)', 0.0)
        mos = row.get('Margin of Safety (%)', 0.0)
        
        if t in TOXIC_TICKERS or (debt > 3.0 and (roe < 8.0 or (pe <= 0 and pb <= 0 and t not in IT_TICKERS))):
            return "🔴 Срочно продать" if in_p else "🔴 Карантин (Риск)"
        if in_p and mos <= -25.0:
            return "🔴 Переоценено (Продать)"
        if in_p and not hold_cycle_df.empty and t in hold_cycle_df['ticker'].values:
            return "⏸️ Дно цикла (Держать)"
        if in_p and share > target_max_pct + 1.0:
            return "🟠 Сократить перевес"
        if in_p and hs < 0.85:
            return "⚠️ Слабый (Кандидат на выход)"
        if t in ['SNGS', 'GAZP', 'FEES', 'UPRO']:
            return "🔒 Структурный дисконт (Наблюдение)"
        if hs >= 1.30 and debt <= 1.5 and (roe >= 15.0 or is_rev) and mos >= 15.0:
            return "🟢 Strong Buy (Income Reversion)" if is_rev else "🟢 Strong Buy (Margin of Safety)"
        if hs >= 1.05 and debt <= 2.0 and mos >= 0.0:
            return "🔵 Наращивать"
        return "🟡 Держать"

    df_ranked['Статус (Действие)'] = df_ranked.apply(assign_action_badge, axis=1)

    # ==========================================
    # ВЕРХНИЙ ЭКЗЕКЬЮТИВ-БАР (СТАТУС И МАКРО)
    # ==========================================
    st.markdown("---")
    h_c1, h_c2, h_c3, h_c4, h_c5 = st.columns(5)
    h_c1.metric(
        "Фаза цикла рынка",
        selected_phase.split(" ")[0],
        f"Ставка ЦБ {market_context.get('KEY_RATE', 'Н/Д')}%"
    )
    regime_display = rules['regime'].split('.')[0] if '.' in rules['regime'] else rules['regime'][:22]
    h_c2.metric(
        "Индекс МосБиржи",
        f"{index_level:,.0f}" if index_level else "Н/Д",
        f"Режим: {regime_display}"
    )
    if my_portfolio:
        h_c3.metric(
            "Капитал акций",
            f"{total_val:,.0f} ₽",
            f"Вложено: {total_inv:,.0f} ₽"
        )
        h_c4.metric(
            "Бумажный PnL",
            f"{pnl_rub:+,.0f} ₽",
            f"{pnl_pct:+.1f}%"
        )
        delta_pct = (port_health - 1.0) * 100
        health_delta_str = f"Сильнее рынка (+{delta_pct:.0f}%)" if port_health >= 1.0 else f"Слабее рынка ({delta_pct:.0f}%)"
        h_c5.metric(
            "Health Score портфеля",
            f"{port_health:.2f}x",
            health_delta_str
        )
    else:
        h_c3.metric("Капитал портфеля", "Ожидает загрузки", "Используйте панель слева")
        h_c4.metric("Бумажный PnL", "—", "Загрузите отчет")
        h_c5.metric("Health Score рынка", f"{df_ranked['Health_Score'].mean():.2f}x", "Среднее по MOEX")
    st.markdown("---")

    # ==========================================
    # 3 ГЛАВНЫХ ЭКРАНА
    # ==========================================
    main_tab1, main_tab2, main_tab3 = st.tabs([
        "🎯 Пульт решений (Что брать / Что продать / Рокировки)",
        "💼 Мой Портфель & Ребалансировка",
        "🔬 Глубокая разведка рынков"
    ])

    with main_tab1:
        # Верхний баннер онлайн-диагностики izi-invest (если подключен MCP)
        mcp_an = st.session_state.get("mcp_analysis")
        if mcp_an and my_portfolio:
            with st.container(border=True):
                mc_c1, mc_c2, mc_c3, mc_c4 = st.columns([1.2, 1.2, 1.2, 1.4])
                p_name = st.session_state.get("mcp_active_portfolio_name", "Ликвидная часть")
                r_top5 = mcp_an.get("risk", {}).get("top5_share", 63.5)
                c_div12 = mcp_an.get("cashflow", {}).get("received_12m_total", 329863.0)
                c_next12 = mcp_an.get("cashflow", {}).get("next_12m_total", 198417.0)
                b_xirr = mcp_an.get("benchmark", {}).get("portfolio_xirr", 6.25)
                b_cbr = mcp_an.get("benchmark", {}).get("cbr_rate", 14.0)

                with mc_c1:
                    st.markdown(f"**⚡ izi-invest: `{p_name}`**")
                    st.caption("Онлайн-синхронизация MCP")
                with mc_c2:
                    st.metric("Концентрация топ-5", f"{r_top5:.1f}%", "HHI 1027 (Умеренная)")
                with mc_c3:
                    st.metric("Дивидендный поток (12 мес)", f"{c_div12:,.0f} ₽", f"Прогноз: {c_next12:,.0f} ₽")
                with mc_c4:
                    st.metric("XIRR vs Ставка ЦБ", f"{b_xirr:+.2f}%", f"ЦБ: {b_cbr:.0f}% (Отставание {b_xirr - b_cbr:+.1f}%)", delta_color="inverse")

        # ------------------------------------------
        # 1. ТРЕХКОЛОНОЧНЫЙ КОМАНДНЫЙ ПУЛЬТ
        # ------------------------------------------
        c_sell, c_buy, c_swap = st.columns([1.0, 1.0, 1.25])
        
        with c_sell:
            st.markdown("#### 🛑 1. Что ПРОДАТЬ / СОКРАТИТЬ")
            st.caption("Балласт портфеля: токсичный долг, слабый ROE и овервейт")
            
            has_sell_signals = False
            
            # 1.1 Срочный выход
            if not urgent_sells_df.empty:
                has_sell_signals = True
                for _, r in urgent_sells_df.iterrows():
                    with st.container(border=True):
                        st.markdown(f"**🔴 {r['ticker']}** | Доля: **{r['Доля в портфеле (%)']:.1f}%** ({r['Текущая Стоимость']:,.0f} ₽)")
                        st.error(f"Долг/EBITDA **{r['Debt_EBITDA']:.1f}x** при ставке {key_rate_for_bl:.1f}% сжигает прибыль компании.")
                        st.caption(f"ROE: **{r['ROE_%']:.1f}%** | PnL: **{r['PnL (%)']:+.1f}%**")
                        st.markdown("👉 **Действие: Полный выход (Ликвидация)**")

            # 1.2 Переоценка по Чёрной Линии (Black Line / Fair Value)
            if not overvalued_bl_df.empty:
                has_sell_signals = True
                for _, r in overvalued_bl_df.iterrows():
                    with st.container(border=True):
                        st.markdown(f"**🔴 {r['ticker']}** | Доля: **{r['Доля в портфеле (%)']:.1f}%** ({r['Текущая Стоимость']:,.0f} ₽)")
                        st.error(f"Биржевая цена **{r['Price']:.1f} ₽** оторвана от Чёрной Линии **{r['Чёрная Линия (₽)']:.1f} ₽** (переоценка {r['Margin of Safety (%)']:+.1f}%).")
                        st.caption(f"Health Score: **{r['Health_Score']:.2f}x** | ROE: **{r['ROE_%']:.1f}%** | P/E: **{r['P_E']:.1f}**")
                        st.markdown("👉 **Действие: Продать / Переложить в лидера с запасом прочности**")

            # 1.3 Сокращение перевеса
            if not overweight_df.empty:
                has_sell_signals = True
                for _, r in overweight_df.iterrows():
                    with st.container(border=True):
                        st.markdown(f"**🟠 {r['ticker']}** | Доля: **{r['Доля в портфеле (%)']:.1f}%** (Лимит {target_max_pct:.0f}%)")
                        st.warning("Концентрация риска: позиция занимает слишком большую долю капитала.")
                        st.caption(f"Стоимость: **{r['Текущая Стоимость']:,.0f} ₽** | PnL: **{r['PnL (%)']:+.1f}%**")
                        st.markdown(f"👉 **Действие: Зафиксировать прибыль / Сократить до {target_max_pct:.0f}%**")

            # 1.4 Слабый бизнес
            if not weak_stocks_df.empty:
                has_sell_signals = True
                for _, r in weak_stocks_df.iterrows():
                    with st.container(border=True):
                        st.markdown(f"**⚠️ {r['ticker']}** | Доля: **{r['Доля в портфеле (%)']:.1f}%** ({r['Текущая Стоимость']:,.0f} ₽)")
                        st.warning(f"Health Score **{r['Health_Score']:.2f}x** уступает рынку. Бизнес не генерирует достаточной отдачи.")
                        st.caption(f"ROE: **{r['ROE_%']:.1f}%** | P/E: **{r['P_E']:.1f}**")
                        st.markdown("👉 **Действие: Сократить / Переложить в лидера**")

            # 1.5 Дно цикла (удержание без продажи!)
            if not hold_cycle_df.empty:
                for _, r in hold_cycle_df.iterrows():
                    with st.container(border=True):
                        st.markdown(f"**⏸️ {r['ticker']}** | Доля: **{r['Доля в портфеле (%)']:.1f}%**")
                        st.info(f"**Дно цикла:** Долг безопасный (Debt/EBITDA {r['Debt_EBITDA']:.1f}x), на счетах кэш. Спад прибыли вызван циклом цен на сырье.")
                        st.markdown("👉 **Действие: Держать, не продавать в убыток!**")

            if my_portfolio and not has_sell_signals:
                st.success("🟢 **Портфель защищен!** В составе нет предбанкротных компаний или токсичного долга.")
            elif not my_portfolio:
                with st.container(border=True):
                    st.markdown("**🛑 Черный список рынка MOEX:**")
                    st.error("Избегайте покупки закредитованных компаний и ловушек с нулевыми дивами (MTLR, SGZH, SMLT, EUTR, PIKK, AFKS)")
                    st.caption(f"При ставке {key_rate_for_bl:.1f}% процентные платежи съедают всю операционную прибыль.")
                    st.info("💡 Загрузите ваш портфель слева, чтобы увидеть персональный аудит бумаг.")

        with c_buy:
            st.markdown("#### 🟢 2. Что КУПИТЬ / НАРАСТИТЬ")
            st.caption("Ядро Value & Income и идеи Income Reversion (без ловушек с низким дивом)")
            
            if not top_buys_df.empty:
                for _, r in top_buys_df.iterrows():
                    t = r['ticker']
                    in_p = r.get('Лоты', 0) > 0
                    share_str = f"В портфеле: {r['Доля в портфеле (%)']:.1f}%" if in_p else "Новая идея (нет в портфеле)"
                    drv_badge = r.get('Драйвер (Value & Income)', '')
                    
                    driver = "Устойчивая отдача на капитал, низкий долг и реальный денежный поток."
                    if t in ['SBER', 'SBERP', 'T', 'SVCB', 'BSPB']:
                        driver = "Высокая рентабельность капитала (ROE > 20%), сильный запас капитала Н1.0 и стабильные дивиденды."
                    elif t in ['TRNFP', 'NMTP']:
                        driver = "Тарифная монополия / портовая перевалка, высокий FCF и устойчивые дивиденды без долгового риска."
                    elif t in ['LKOH', 'ROSN', 'TATN']:
                        driver = "Value & Income / Income Reversion: мощный FCF при минимальном долге и дивидендная доходность."
                    elif t in ['MDMG', 'X5', 'FIVE']:
                        driver = "Защита от инфляции: рост выручки в потребсекторе/медицине, высокий ROE и регулярный кэш."
                    elif t in ['HEAD', 'YNDX', 'YDEX', 'DIAS']:
                        driver = "Высокие темпы роста выручки, низкая долговая нагрузка и высокая маржа."
                    
                    mos_val = r.get('Margin of Safety (%)', 0.0)
                    bl_val = r.get('Чёрная Линия (₽)', 0.0)
                    div_y = r.get('Div_Yield_%', 0.0)
                    fcf_y = r.get('FCF_Yield_%')
                    fcf_str = f" | FCF: **{fcf_y:.1f}%**" if pd.notna(fcf_y) else ""
                    with st.container(border=True):
                        st.markdown(f"**🟢 {t}** | Чёрная Линия: **{bl_val:.1f} ₽** (Запас: **{mos_val:+.1f}%**)")
                        st.caption(f"{share_str} | `{drv_badge}` | Health: **{r['Health_Score']:.2f}x** | Дивы: **{div_y:.1f}%**{fcf_str}")
                        st.success(f"**Почему брать:** {driver}")
                        if pd.notna(r.get('Поток (OrderFlow)')):
                            st.caption(f"Order Flow: `{r['Поток (OrderFlow)']}`")
                        action_txt = f"Нарастить до {r['Идеальная доля (%)']:.1f}%" if in_p else f"Открыть позицию (цель {r['Идеальная доля (%)']:.1f}%)"
                        st.markdown(f"👉 **Действие: {action_txt}**")
            else:
                st.info("Нет доступных рекомендаций к покупке при текущих фильтрах.")

        with c_swap:
            st.markdown("#### 🔄 3. ГОТОВАЯ РОКИРОВКА (СВОП)")
            st.caption("Пошаговые торговые сценарии перекладки капитала")
            
            if smart_swaps:
                for idx, sw in enumerate(smart_swaps[:3], 1):
                    with st.container(border=True):
                        st.markdown(f"##### Сценарий #{idx}: {sw['badge']}")
                        st.markdown(f"**Продать:** `{sw['sell_ticker']}` ➔ высвободить **{sw['sell_val']:,.0f} ₽**")
                        st.caption(f"Причина: {sw['sell_reason']}")
                        st.markdown(f"⬇️ **Переложить в:** `{sw['buy_ticker']}` ➔ **{sw['buy_lots']}** лотов (~{sw['buy_val']:,.0f} ₽)")
                        if sw.get('rem_cash', 0) > 100:
                            st.caption(f"Остаток в фонд ликвидности / кэш: {sw['rem_cash']:,.0f} ₽")
                        st.info(f"📈 **Результат рокировки:** {sw['effect']}")
                        
                with st.expander("📋 Шпаргалка для ввода заявок брокеру", expanded=False):
                    cheat_text = ""
                    for idx, sw in enumerate(smart_swaps[:3], 1):
                        cheat_text += f"{idx}. ПРОДАТЬ {sw['sell_ticker']} на сумму ~{sw['sell_val']:,.0f} ₽\n"
                        cheat_text += f"   КУПИТЬ {sw['buy_ticker']} в объеме {sw['buy_lots']} лотов\n\n"
                    st.code(cheat_text, language="text")
            else:
                with st.container(border=True):
                    st.markdown("##### 💡 Модельный портфель (Базовый сплит)")
                    st.markdown("Ваш портфель сбалансирован, срочных рокировок не требуется.")
                    st.info("Свежие притоки капитала направляйте в топ-3 бумаги по Health Score: " +
                            ", ".join(f"`{t}`" for t in top_buys_df['ticker'].head(3)))

        # ------------------------------------------
        # 1.5 ГРАФИК КОТИРОВОК VS ЧЁРНАЯ ЛИНИЯ (BLACK LINE)
        # ------------------------------------------
        st.markdown("---")
        st.markdown("### 🖤 График котировок vs Чёрная Линия (Black Line / Fair Value)")
        st.caption("Фундаментальная внутренняя стоимость бизнеса из финансовых отчетов vs Рыночная биржевая цена. Включайте и отключайте Чёрную линию одним кликом.")

        candidate_tickers = []
        if not top_buys_df.empty:
            candidate_tickers.extend(top_buys_df['ticker'].tolist())
        if my_portfolio:
            candidate_tickers.extend([t for t in portfolio_tickers_list if t not in candidate_tickers])
        all_tickers = df_ranked['ticker'].tolist()
        candidate_tickers.extend([t for t in all_tickers if t not in candidate_tickers])

        c_sel_t, _ = st.columns([2, 2])
        with c_sel_t:
            selected_bl_ticker = st.selectbox(
                "Выберите актив для детального анализа Чёрной линии:",
                options=candidate_tickers,
                index=0,
                key="main_bl_ticker_select",
                help="Выберите любую акцию из вашего портфеля или широкого рынка MOEX для просмотра котировок и наложения Чёрной линии"
            )

        if selected_bl_ticker:
            row_bl = df_ranked[df_ranked['ticker'] == selected_bl_ticker]
            fund_row = row_bl.iloc[0] if not row_bl.empty else None
            p_curr = fund_row.get('Price', 0.0) if fund_row is not None else 0.0

            render_black_line_widget(
                ticker=selected_bl_ticker,
                current_price=p_curr,
                fund_row=fund_row,
                key_rate=key_rate_for_bl,
                default_show=True,
                key_prefix="main_screen"
            )

        # ------------------------------------------
        # 2. СВЕТОФОР АКТИВОВ (TRAFFIC LIGHT MATRIX)
        # ------------------------------------------
        st.markdown("---")
        st.markdown("### 🚥 Светофор активов (Traffic Light Market Matrix)")
        st.caption("Комплексный статус каждой акции: мгновенное понимание, что докупать, что удерживать, а что сбрасывать.")
        
        t_f1, t_f2 = st.columns([2, 1])
        with t_f1:
            traffic_filter = st.radio(
                "Фильтр таблицы:",
                ["Все активы", "🟢 Покупки (Buy)", "⏸️ Дно цикла / Держать", "🔴 Продажи / Риск", "💼 Мой портфель"],
                horizontal=True
            )
        
        df_tl = df_ranked.copy()
        if traffic_filter == "🟢 Покупки (Buy)":
            df_tl = df_tl[df_tl['Статус (Действие)'].str.contains("Buy|Наращивать", case=False, na=False)]
        elif traffic_filter == "⏸️ Дно цикла / Держать":
            df_tl = df_tl[df_tl['Статус (Действие)'].str.contains("Дно|Держать", case=False, na=False)]
        elif traffic_filter == "🔴 Продажи / Риск":
            df_tl = df_tl[df_tl['Статус (Действие)'].str.contains("продать|Карантин|Слабый|Сократить", case=False, na=False)]
        elif traffic_filter == "💼 Мой портфель":
            df_tl = df_tl[df_tl['Лоты'] > 0]
            
        tl_cols = [
            "ticker", "Статус (Действие)", "Драйвер (Value & Income)", "Price", "Чёрная Линия (₽)", "Margin of Safety (%)",
            "Доля в портфеле (%)", "Идеальная доля (%)",
            "PnL (%)", "Health_Score", "Div_Yield_%", "FCF_Yield_%", "ROE_%", "Debt_EBITDA", "P_E", "Тренд", "Поток (OrderFlow)"
        ]
        if not my_portfolio:
            tl_cols = [
                "ticker", "Статус (Действие)", "Драйвер (Value & Income)", "Price", "Чёрная Линия (₽)", "Margin of Safety (%)",
                "Идеальная доля (%)", "Health_Score", "Div_Yield_%", "FCF_Yield_%", "ROE_%", "Debt_EBITDA", "P_E", "Тренд", "Поток (OrderFlow)"
            ]
            
        st.dataframe(
            df_tl[[c for c in tl_cols if c in df_tl.columns]],
            width="stretch",
            hide_index=True,
            column_config={
                "Price": st.column_config.NumberColumn(
                    "Цена MOEX",
                    format="%.2f ₽",
                    help="Текущая котировка акции на МосБирже"
                ),
                "Чёрная Линия (₽)": st.column_config.NumberColumn(
                    "Чёрная Линия (₽)",
                    format="%.1f ₽",
                    help="Справедливая внутренняя стоимость бизнеса из финансовых отчетов и мультипликаторов (Black Line)"
                ),
                "Margin of Safety (%)": st.column_config.NumberColumn(
                    "Margin of Safety (%)",
                    format="%+.1f%%",
                    help="Запас прочности по Грэму: положительное значение — недооценка (зона покупок), отрицательное — переоценка"
                ),
                "Health_Score": st.column_config.NumberColumn(
                    "Health_Score",
                    help="Комплексный балл здоровья бизнеса. База = 1.0. Умножается на коэффициенты за рентабельность, долг, дивиденды, Order Flow и тренд."
                ),
                "Статус (Действие)": st.column_config.TextColumn(
                    "Статус (Действие)",
                    help="Сигнал алгоритма: 🟢 Strong Buy, 🔵 Наращивать, ⏸️ Дно цикла, 🟡 Держать, 🟠 Сократить, 🔴 Продать"
                )
            }
        )
        
        with st.expander("📊 График распределения Health Score по всем акциям", expanded=False):
            st.bar_chart(data=df_ranked, x="ticker", y="Health_Score")
            
        with st.expander("🌐 Макро-барометр сырья, ставок и инфляции", expanded=False):
            b_c1, b_c2, b_c3, b_c4 = st.columns(4)
            b_c1.metric("RTSI", f"{market_context.get('RTSI', 0):,.0f}" if market_context.get('RTSI') else "Н/Д")
            b_c2.metric("USD/RUB", f"{usd_rate:.2f}" if usd_rate else "Н/Д")
            b_c3.metric("Urals", f"${market_context.get('URALS', 0):.2f}" if market_context.get('URALS') else "Н/Д")
            b_c4.metric("Золото", f"${market_context.get('GOLD', 0):,.0f}" if market_context.get('GOLD') else "Н/Д")
            b_c5, b_c6, b_c7, b_c8 = st.columns(4)
            b_c5.metric("Сталь HRC", f"${market_context.get('STEEL', 0):,.0f}" if market_context.get('STEEL') else "Н/Д")
            b_c6.metric("Инфляция (Р)", f"{market_context.get('INFLATION_REAL', 0)}%" if market_context.get('INFLATION_REAL') else "Н/Д")
            b_c7.metric("Кэш норма", f"{rules['cash_target']*100:.0f}%")
            b_c8.metric("Облигации норма", f"{rules['bond_target']*100:.0f}%")
            
        with st.expander("ℹ️ Методология: Как рассчитывается Health Score?", expanded=False):
            st.markdown(HEALTH_SCORE_EXPLANATION)

        with st.expander(f"📋 Ликвидные тикеры MOEX ({len(moex_tickers)})", expanded=False):
            st.dataframe(
                moex_universe[["ticker", "list_level", "turnover_mln"]].rename(
                    columns={
                        "ticker": "Тикер",
                        "list_level": "Эшелон",
                        "turnover_mln": "Оборот сегодня, млн ₽",
                    }
                ),
                width="stretch",
                hide_index=True,
            )

    with main_tab2:
        st.subheader("💼 Аудит структуры капитала и «Штанги» портфеля")
        st.caption(
            f"Подход Value & Income + Валютный/Золотой щит (0% длинных RUB ОФЗ против турецкого риска): {rules['bond_currency']}"
        )
        
        if my_portfolio:
            port_r1, port_r2, port_r3, port_r4, port_r5 = st.columns(5)
            full_cap = total_val + my_reserves_invested + my_blocked_invested
            port_r1.metric("📈 Акции (Альфа-Банк)", f"{total_val:,.0f} ₽", f"{pnl_rub:+,.0f} ₽ ({pnl_pct:+.1f}%)")
            port_r2.metric("💵 Валютный щит (ВТБ)", f"{my_reserves_invested:,.0f} ₽", "Хедж девальвации / Облигации")
            port_r3.metric("🔒 Заблокировано FinEx", f"{my_blocked_invested:,.0f} ₽", "Иностранные фонды (Альфа)")
            port_r4.metric("💰 Свободный кэш", f"{cash_rub:,.0f} ₽", "Готов к покупкам")
            port_r5.metric("🏛️ Всего капитал", f"{full_cap:,.0f} ₽", f"Ликвидный: {total_val + my_reserves_invested:,.0f} ₽")
            
            st.markdown("---")
            
            with st.expander("🎯 Карта фундаментальной оценки (ROE vs P/E scatter plot)", expanded=True):
                st.caption("По оси X — **Оценка (P/E)**: левее = дешевле. По оси Y — **Эффективность (ROE)**: выше = лучше. Размер точки пропорционален **Health Score**. Ваш портфель выделен ярким цветом.")
                map_df = df_ranked.copy()
                port_active_set = set(df_port['ticker'].values) if not df_port.empty else set()
                map_df['Категория'] = map_df['ticker'].apply(lambda t: "Мой портфель" if t in port_active_set else "Кандидаты с рынка")
                map_df['P/E (масштабированный)'] = map_df['P_E'].clip(lower=-40, upper=40)
                map_df['Здоровье'] = map_df['Health_Score'].clip(lower=0.1) * 10
                
                domain = ['Мой портфель', 'Кандидаты с рынка']
                range_ = ['#FF3366', '#1E88E5']
                
                base = alt.Chart(map_df).encode(
                    x=alt.X('P/E (масштабированный):Q', title='P/E (Оценка)'),
                    y=alt.Y('ROE_%:Q', title='ROE (Эффективность)'),
                    color=alt.Color('Категория:N', scale=alt.Scale(domain=domain, range=range_)),
                    tooltip=['ticker', 'Health_Score', 'P_E', 'ROE_%', 'Категория']
                )
                points = base.mark_circle().encode(size=alt.Size('Здоровье:Q', legend=None))
                text = base.mark_text(align='left', baseline='middle', dx=9, fontSize=11, fontWeight='bold').encode(text='ticker:N')
                st.altair_chart((points + text).interactive(), width="stretch")

            with st.expander("⚖️ Сравнение долей: Текущая доля vs Идеальная доля (%)", expanded=True):
                weight_comp_df = df_ranked[df_ranked['Лоты'] > 0][['ticker', 'Доля в портфеле (%)', 'Идеальная доля (%)']].copy()
                if not weight_comp_df.empty:
                    weight_melted = weight_comp_df.melt(id_vars=['ticker'], value_vars=['Доля в портфеле (%)', 'Идеальная доля (%)'], var_name='Тип доли', value_name='Процент')
                    bar_w = alt.Chart(weight_melted).mark_bar().encode(
                        x=alt.X('ticker:N', title='Тикер'),
                        y=alt.Y('Процент:Q', title='% от портфеля'),
                        color=alt.Color('Тип доли:N', scale=alt.Scale(domain=['Доля в портфеле (%)', 'Идеальная доля (%)'], range=['#FF8A65', '#4CAF50'])),
                        xOffset='Тип доли:N'
                    ).properties(height=320)
                    st.altair_chart(bar_w, width="stretch")

            st.markdown("##### 📋 Расчет целевых объемов позиций")
            st.caption(f"Топ-{n_assets} активов по Health Score | Акционерная доля: {rules['equity_target']*100:.0f}% от капитала ({capital:,.0f} ₽)")
            st.dataframe(position_df, width="stretch", hide_index=True)
            
            p_lnk1, p_lnk2 = st.columns(2)
            with p_lnk1:
                st.page_link("pages/3_⏳_Бэктест_Стратегии.py", label="⏳ Запустить исторический бэктест вашего портфеля vs IMOEX", icon="⏳")
            with p_lnk2:
                st.page_link("pages/4_💼_Реальный_Портфель_и_Сделки.py", label="💼 Анализ реальных сделок FIFO и зеркальный бенчмарк", icon="💼")
        else:
            st.info("Загрузите файл портфеля на боковой панели слева (или включите демо-портфель), чтобы активировать детальный аудит долей.")
            st.markdown("##### 📋 Модельный портфель по Health Score")
            st.caption(f"Топ-{n_assets} активов рынка для формирования сбалансированного портфеля:")
            st.dataframe(position_df, width="stretch", hide_index=True)

    with main_tab3:
        sub_of, sub_banks, sub_tankers, sub_debt, sub_foundry, sub_screener = st.tabs([
            "🌊 Order Flow (Magellan PRO)",
            "🏦 Банки ЦБ РФ (РСБУ)",
            "🚢 Танкеры & Нефть (TankerMap)",
            "💳 Долг & БПИФ (Рынок капитала)",
            "📊 Фундаментал (Data Foundry)",
            "🗺️ Тепловая карта рынка (Скринер)"
        ])

        with sub_of:
            # 🌊 ORDER FLOW (Russian Magellan PRO)
            st.subheader("🌊 Микроструктура торгов: Order Flow & Умные деньги")
            st.caption("Анализ агрессивных покупок/продаж и поглощения навесов в стакане по данным Russian Magellan PRO.")
            
            of_col_a, of_col_b = st.columns([3, 1])
            with of_col_a:
                st.markdown("Мониторинг показывает, **куда реально перетекает ликвидность**: крупный игрок может скрытно скупать бумагу при падающей цене (*Абсорбция / Накопление*) или распределять позицию толпе (*Скрытый сброс*).")
            with of_col_b:
                of_period = st.radio("Период Order Flow:", ["Сегодня (с открытия)", "Неделя (кумулятивно)"], horizontal=True)

            active_period_code = "today" if of_period.startswith("Сегодня") else "week"
            of_raw = fetch_magellan_order_flow(active_period_code)

            if of_raw:
                of_rows = []
                for t, info in of_raw.items():
                    if t in selected_tickers or not selected_tickers:
                        bv_m = info.get("bv", 0) / 1_000_000.0
                        sv_m = info.get("sv", 0) / 1_000_000.0
                        delta_m = info.get("delta", 0) / 1_000_000.0
                        total_m = bv_m + sv_m
                        big_bv = info.get("big_bv", 0.0)
                        big_sv = info.get("big_sv", 0.0)
                        big_delta_m = (big_bv - big_sv) / 1_000_000.0
                        if total_m > 0:
                            of_rows.append({
                                "Тикер": t,
                                "Цена, ₽": info.get("last_price"),
                                "Изм, %": info.get("price_chng"),
                                "Покупки, млн ₽": round(bv_m, 2),
                                "Продажи, млн ₽": round(sv_m, 2),
                                "Дельта, млн ₽": round(delta_m, 2),
                                "Киты дельта, млн ₽": round(big_delta_m, 2),
                                "Доля покупок, %": info.get("buy_ratio"),
                                "Сигнал": info.get("reading_label", "—"),
                                "Механика": info.get("reading_explain", ""),
                                "key": info.get("reading_key", "na")
                            })

                df_of_table = pd.DataFrame(of_rows)
                if not df_of_table.empty:
                    total_buy = df_of_table["Покупки, млн ₽"].sum()
                    total_sell = df_of_table["Продажи, млн ₽"].sum()
                    net_delta = df_of_table["Дельта, млн ₽"].sum()
                    avg_buy_pct = (total_buy / (total_buy + total_sell) * 100) if (total_buy + total_sell) > 0 else 50.0

                    m1, m2, m3, m4 = st.columns(4)
                    m1.metric("Суммарные покупки", f"{total_buy:,.1f} млн ₽")
                    m2.metric("Суммарные продажи", f"{total_sell:,.1f} млн ₽")
                    m3.metric("Чистая дельта (Buy - Sell)", f"{net_delta:+,.1f} млн ₽", "Перевес покупателей" if net_delta > 0 else "Давление продавцов")
                    m4.metric("Доля агрессивных покупок", f"{avg_buy_pct:.1f}%")

                    st.markdown("---")
                    top_accum = df_of_table[df_of_table["key"] == "accum"].sort_values(by="Дельта, млн ₽", ascending=False).head(3)
                    top_distr = df_of_table[df_of_table["key"] == "distr"].sort_values(by="Дельта, млн ₽", ascending=True).head(3)

                    c_acc, c_dis = st.columns(2)
                    with c_acc:
                        st.success("🟢 **Лидеры накопления / поглощения продаж:**")
                        if not top_accum.empty:
                            for _, r in top_accum.iterrows():
                                st.write(f"• **{r['Тикер']}**: Дельта {r['Дельта, млн ₽']:+,.1f}M ₽ (Покупки {r['Доля покупок, %']}%) — *{r['Сигнал']}*")
                        else:
                            st.write("На выбранном срезе выраженных накоплений не зафиксировано.")

                    with c_dis:
                        st.error("🔴 **Лидеры скрытого сброса (распределения):**")
                        if not top_distr.empty:
                            for _, r in top_distr.iterrows():
                                st.write(f"• **{r['Тикер']}**: Дельта {r['Дельта, млн ₽']:+,.1f}M ₽ (Покупки {r['Доля покупок, %']}%) — *{r['Сигнал']}*")
                        else:
                            st.write("На выбранном срезе выраженных сбросов не зафиксировано.")

                    st.markdown("##### 📋 Детальная лента объемов и сигналов микроструктуры")
                    st.dataframe(
                        df_of_table.drop(columns=["key"]).sort_values(by="Дельта, млн ₽", ascending=False),
                        width="stretch",
                        hide_index=True,
                        column_config={
                            "Дельта, млн ₽": st.column_config.NumberColumn(
                                "Дельта, млн ₽",
                                help="Разница между объемом покупок по цене ask и продаж по цене bid."
                            ),
                            "Механика": st.column_config.TextColumn(
                                "Механика",
                                help="Алгоритмическая интерпретация поведения маркетмейкеров и крупных игроков."
                            )
                        }
                    )
            else:
                st.info("Данные Order Flow временно обновляются...")

        with sub_banks:
            # 🏦 БАНКИ ЦБ РФ (РСБУ)
            st.subheader("🏦 Финансовый сектор по РСБУ (Формы 101/102 ЦБ РФ)")
            st.caption("Помесячная отчетность банков из первоисточника Банка России через Russian Magellan PRO. Обновляется ежемесячно без ожидания квартальных МСФО.")

            banks_summary = fetch_magellan_banks_summary()
            if banks_summary:
                b_cols = st.columns(min(len(banks_summary), 5))
                for idx, (t, b) in enumerate(list(banks_summary.items())[:5]):
                    with b_cols[idx]:
                        ytd_mlrd = b.get("ytd_profit_rub", 0) / 1_000_000_000.0
                        growth = b.get("ytd_growth_pct")
                        st.metric(
                            label=f"{b.get('name')} ({t})",
                            value=f"{ytd_mlrd:,.1f} млрд ₽",
                            delta=f"{growth:+.1f}% г/г" if growth is not None else None
                        )

                st.markdown("---")
                sel_bank_ticker = st.selectbox(
                    "Выберите банк для детального аудита нормативов и капитала:",
                    options=list(banks_summary.keys()),
                    index=0
                )

                bank_detail = fetch_magellan_bank_details(sel_bank_ticker)
                if bank_detail:
                    st.markdown(f"#### 🏛️ {bank_detail.get('name')} — Показатели на {bank_detail.get('last_month')}")
                    kpi_c1, kpi_c2, kpi_c3, kpi_c4 = st.columns(4)

                    roe_val = bank_detail.get("roe_ltm")
                    kpi_c1.metric("ROE LTM (по ЦБ)", f"{roe_val}%" if roe_val else "Н/Д", "Норма > 15%" if (roe_val or 0) >= 15 else "Слабая рентабельность")

                    h10_val = bank_detail.get("h1_0")
                    h10_status = "🛡️ Избыток (>12%)" if (h10_val or 0) >= 12.0 else ("⚠️ В норме" if (h10_val or 0) >= 9.5 else "🚨 Риск дефицита")
                    kpi_c2.metric("Достаточность H1.0", f"{h10_val:.2f}%" if h10_val else "Н/Д", h10_status)

                    h11_val = bank_detail.get("h1_1")
                    kpi_c3.metric("Базовый капитал H1.1", f"{h11_val:.2f}%" if h11_val else "Н/Д", "Норматив ЦБ: мин 4.5%")

                    overdue = bank_detail.get("overdue_pct")
                    cover = bank_detail.get("reserve_cover")
                    kpi_c4.metric("Просрочка / Покрытие", f"{overdue}% / {cover}%" if overdue else "Н/Д")

                    st.info(f"💡 **Влияние на Health Score:** Банк оценивается по форме 101/102 ЦБ РФ. Норматив H1.0 = {h10_val:.2f}% ({h10_status}), просрочка = {overdue}%. При H1.0 ≥ 12% и просрочке < 3.5% банк получает совокупную премию к дивидендному здоровью до +20%. При дефиците капитала (H1.0 < 9.5%) начисляется штраф -30%.")

                    points = bank_detail.get("points", [])
                    if points:
                        df_pts = pd.DataFrame(points)
                        df_pts["Чистая прибыль за месяц, млрд ₽"] = df_pts["monthly"].fillna(0) / 1_000_000.0
                        st.markdown("##### 📈 Помесячная динамика чистой прибыли (Форма 102 ЦБ РФ)")
                        st.bar_chart(df_pts, x="month", y="Чистая прибыль за месяц, млрд ₽")
            else:
                st.info("Данные по банковскому сектору формируются...")

        with sub_tankers:
            # 🚢 НЕФТЯНОЙ ФЛОТ & ЛОГИСТИКА (TankerMap)
            st.subheader("🚢 Нефтяной флот & Логистика танкерного экспорта (TankerMap)")
            st.caption("Спутниковый трекинг AIS морского экспорта сырой нефти, нефтепродуктов и СПГ из портов РФ.")

            t_col1, t_col2, t_col3, t_col4 = st.columns(4)
            ru_vessels_cnt = tanker_stats.get("total_ru_vessels", 0)
            crude_dwt_m = (tanker_stats.get("loaded_crude_dwt", 0)) / 1_000_000.0
            prod_dwt_m = (tanker_stats.get("loaded_prod_dwt", 0)) / 1_000_000.0
            sanctioned_cnt = tanker_stats.get("sanctioned_vessels_global", 0)

            t_col1.metric("Танкеров на маршрутах РФ", f"{ru_vessels_cnt} судов", "Стабильный экспорт" if ru_vessels_cnt > 120 else "Замедление")
            t_col2.metric("Сырая нефть в море", f"{crude_dwt_m:.2f} млн тонн", "Urals / ВСТО / КТК")
            t_col3.metric("Нефтепродукты & СПГ", f"{prod_dwt_m:.2f} млн тонн", "Дизель / Мазут / LNG")
            t_col4.metric("Теневой / Санкционный флот", f"{sanctioned_cnt} судов", "Глобальный мониторинг")

            st.info(f"💡 **Влияние на Health Score:** Спутниковый трекинг AIS отслеживает {ru_vessels_cnt} танкеров на маршрутах экспорта РФ и {crude_dwt_m:.2f} млн тонн сырой нефти в море. Экспортный коридор стабилен ➡️ Нефтяные мейджоры (ROSN, LKOH, SIBN, TATN, SNGS, BANE) получают премию +8% к Health Score за надежность сбыта; портовые терминалы (TRNFP, NMTP) — премию +12%; танкерный перевозчик (FLOT) — премию до +15% (с учетом обхода Суэца вокруг Африки).")

            st.markdown("---")
            port_col, choke_col = st.columns([1, 1])

            with port_col:
                st.markdown("##### ⚓ Активность в экспортных хабах РФ")
                port_breakdown = tanker_stats.get("port_distribution", {})
                if port_breakdown:
                    df_ports = pd.DataFrame([
                        {"Морской бассейн": k, "Танкеров": v} for k, v in port_breakdown.items()
                    ])
                    st.bar_chart(df_ports, x="Морской бассейн", y="Танкеров")
                else:
                    st.write("Данные распределения по портам обновляются...")

            with choke_col:
                st.markdown("##### 🌊 Мониторинг узких проливов (Chokepoints)")
                choke_summary = fetch_tankermap_chokepoints()
                if choke_summary:
                    c_rows = []
                    names_map = {
                        "hormuz": "Ормузский пролив (Hormuz)",
                        "suez": "Суэцкий канал (Suez)",
                        "malacca": "Малаккский пролив (Malacca)",
                        "bab_el_mandeb": "Баб-эль-Мандеб (Красное море)",
                        "danish_straits": "Датские проливы (Балтика)"
                    }
                    for k, item in choke_summary.items():
                        if k in names_map:
                            c_rows.append({
                                "Пролив": names_map[k],
                                "Судов сейчас": item.get("live_count", 0),
                                "В среднем / день": item.get("avg_daily", 0),
                                "Тренд трафика": f"{item.get('trend_pct', 0):+.1f}%"
                            })
                    if c_rows:
                        st.dataframe(pd.DataFrame(c_rows), width="stretch", hide_index=True)
                else:
                    st.write("Данные по проливам загружаются...")

            st.markdown("---")
            st.markdown("##### 📰 Морские новости и геополитические алерты (TankerMap Research)")
            t_news = fetch_tankermap_news()
            if t_news:
                for n_item in t_news[:5]:
                    with st.expander(f"📍 {n_item.get('published_at', '')[:10]} | {n_item.get('title')}", expanded=False):
                        st.write(f"**Тематика:** `{n_item.get('primary_topic', 'shipping')}` │ **Тег:** `{n_item.get('tag', 'market')}`")
                        st.write(n_item.get("excerpt", ""))
            else:
                st.write("Лента морских новостей обновляется...")

        with sub_debt:
            # 💳 ДОЛГОВОЙ РЫНОК & ИНСТИТУЦИОНАЛЬНЫЕ БПИФ
            st.subheader("💳 Рынок корпоративного долга & Институциональные БПИФ")
            st.caption("Опережающий мониторинг долгового стресса по корпоративным облигациям (MOEX TQCB + Magellan) и притоков капитала институциональных ETF фондов.")

            b_cnt_total = sum(b.get("bond_count", 0) for b in magellan_bonds.values()) if magellan_bonds else 0
            critical_cnt = sum(1 for b in magellan_bonds.values() if b.get("risk_level") in ["CRITICAL", "HIGH"]) if magellan_bonds else 0
            top_inflows = [t for t, f in magellan_funds.items() if f.get("net_weight_change", 0) >= 1.0][:3] if magellan_funds else []

            tb1, tb2, tb3, tb4 = st.columns(4)
            tb1.metric("Облигационных выпусков", f"{b_cnt_total} бумаг", "Связка с акциями MOEX")
            tb2.metric("Эмитентов в долговом стрессе", f"{critical_cnt} комп.", "YTM > 28% (высокий риск)" if critical_cnt > 0 else "Рынок стабилен")
            tb3.metric("Лидеры притоков БПИФ", ", ".join(top_inflows) if top_inflows else "Н/Д", "Институциональный спрос")
            tb4.metric("Сетевые компании (ИПР)", f"{len(magellan_ipr)} комп.", "Форма 19 Минэнерго")

            st.markdown("---")
            st.markdown("#### 🚨 Радар долгового стресса (Корпоративные облигации эмитентов)")
            st.write("Рынок долга умнее рынка акций: **если доходность облигаций компании взлетает до 30–50%+**, держатели бондов закладывают дефолт или жесткую реструктуризацию. Акции таких эмитентов получают суровый штраф к Health Score.")

            if magellan_bonds:
                b_rows = []
                for t, b in magellan_bonds.items():
                    if t in selected_tickers or not selected_tickers:
                        b_rows.append({
                            "Тикер": t,
                            "Выпусков бондов": b.get("bond_count", 0),
                            "Средняя YTM, %": b.get("avg_ytm"),
                            "Макс YTM, %": b.get("max_ytm"),
                            "Статус риска": b.get("distress_status"),
                            "Пример выпуска": f"{b.get('sample_name', '')} ({b.get('sample_secid', '')})",
                            "Множитель Health Score": f"×{b.get('health_mult', 1.0):.2f}"
                        })
                df_bonds_ui = pd.DataFrame(b_rows)
                if not df_bonds_ui.empty:
                    st.dataframe(
                        df_bonds_ui.sort_values(by="Макс YTM, %", ascending=False),
                        width="stretch",
                        hide_index=True,
                        column_config={
                            "Макс YTM, %": st.column_config.NumberColumn(
                                "Макс YTM, %",
                                help="Пиковая доходность к погашению среди всех обращающихся выпусков эмитента."
                            ),
                            "Множитель Health Score": st.column_config.TextColumn(
                                "Множитель Health Score",
                                help="Влияние долгового стресса на итоговый инвестиционный балл акции."
                            )
                        }
                    )
            else:
                st.info("Данные по корпоративным облигациям формируются...")

            st.markdown("---")
            b_col_funds, b_col_ipr = st.columns([3, 2])

            with b_col_funds:
                st.markdown("#### 🏛️ Радар институциональных фондов (БПИФ)")
                st.caption("Позиции и раскрытия изменений весов в фондах Т-Капитал («Трендовые», «Дивидендные», «Второй эшелон»).")
                if magellan_funds:
                    f_rows = []
                    for t, f in magellan_funds.items():
                        if t in selected_tickers or not selected_tickers:
                            f_rows.append({
                                "Тикер": t,
                                "Фонды-держатели": ", ".join(f.get("funds", [])),
                                "Изм. веса, %": f.get("net_weight_change", 0.0),
                                "Действие": f.get("action", "—"),
                                "Объем в фондах, млн ₽": round(f.get("total_val_rub", 0) / 1_000_000.0, 1)
                            })
                    df_funds_ui = pd.DataFrame(f_rows)
                    if not df_funds_ui.empty:
                        st.dataframe(
                            df_funds_ui.sort_values(by="Изм. веса, %", ascending=False),
                            width="stretch",
                            hide_index=True
                        )
                else:
                    st.write("Данные БПИФ обновляются...")

            with b_col_ipr:
                st.markdown("#### ⚡ Инвестпрограммы сетевых компаний (ИПР)")
                st.caption("Контроль капзатрат и дивидендов сетевых компаний по форме 19.")
                if magellan_ipr:
                    ipr_rows = [
                        {"Тикер": t, "Компания": item.get("name"), "Статус дивидендов": item.get("div_status"), "Горизонт": item.get("nearest_year")}
                        for t, item in magellan_ipr.items()
                    ]
                    st.dataframe(pd.DataFrame(ipr_rows), width="stretch", hide_index=True)
                else:
                    st.write("Данные ИПР обновляются...")

        with sub_foundry:
            # 📊 ФУНДАМЕНТАЛЬНЫЙ АНАЛИЗ (DATA FOUNDRY)
            st.subheader("📊 Фундаментальный анализ компании (Data Foundry)")
            st.caption("Официальные аудированные показатели эмитентов РФ (МСФО/РСБУ) из публичного финансового MCP-сервера Data Foundry.")

            foundry_status = get_foundry_status()
            dataset_version = foundry_status.get("dataset_version")

            if not foundry_status.get("ok") or not dataset_version:
                st.warning(
                    "⚠️ Сервер Data Foundry временно недоступен или не отвечает. "
                    "Основной функционал дашборда (котировки MOEX, индикаторы, портфель) продолжает работать штатно (Graceful Degradation)."
                )
                if foundry_status.get("error"):
                    st.caption(f"Техническая деталь: `{foundry_status.get('error')}`")
                if st.button("🔄 Повторить проверку Data Foundry", key="btn_retry_foundry"):
                    clear_foundry_cache()
                    st.rerun()
            else:
                if not foundry_status.get("is_schema_supported"):
                    st.warning(
                        f"⚠️ Версия схемы данных сервера ({foundry_status.get('schema_version')}) отличается от ожидаемой (v1)."
                    )

                f_col1, f_col2, f_col3 = st.columns([2, 2, 1])
                with f_col1:
                    avail_tickers = [t for t in selected_tickers if t in moex_tickers] if selected_tickers else moex_tickers
                    if not avail_tickers:
                        avail_tickers = moex_tickers or list(PORTFOLIO_TICKERS)
                    def_idx = 0
                    if "SBER" in avail_tickers:
                        def_idx = avail_tickers.index("SBER")
                    elif "LKOH" in avail_tickers:
                        def_idx = avail_tickers.index("LKOH")

                    chosen_ticker = st.selectbox(
                        "Выберите акцию / эмитент:",
                        options=avail_tickers,
                        index=def_idx,
                        key="foundry_ticker_select"
                    )

                with f_col2:
                    basis_choice = st.radio(
                        "Стандарт отчётности:",
                        ["МСФО (IFRS)", "РСБУ (RAS)"],
                        horizontal=True,
                        key="foundry_basis_choice"
                    )
                    chosen_basis = "IFRS" if "IFRS" in basis_choice else "RAS"

                with f_col3:
                    st.write("")
                    st.write("")
                    if st.button("🔄 Сбросить кэш", key="btn_refresh_foundry_cache", help="Сбросить кэш healthz и запросить свежие данные"):
                        clear_foundry_cache()
                        st.rerun()

                if chosen_ticker:
                    with st.spinner(f"Загружаю финансовые ряды для {chosen_ticker} ({chosen_basis})..."):
                        profile = get_company_fundamental_profile(
                            chosen_ticker,
                            dataset_version,
                            accounting_basis=chosen_basis
                        )

                    is_bank = profile.get("is_bank", False)
                    company_name = profile.get("company_name", chosen_ticker)
                    avail_standards = profile.get("available_standards", [])
                    periods = profile.get("periods", [])
                    rows = profile.get("rows", [])

                    sector_label = "🏦 Банковский / Финансовый сектор" if is_bank else "🏭 Реальный сектор экономики"
                    st.markdown(f"### {company_name} (`{chosen_ticker}`) — {sector_label}")

                    if avail_standards:
                        standards_badge = " • ".join(
                            [f"**{std}**" if std == chosen_basis else std for std in avail_standards]
                        )
                        st.caption(f"Стандарты отчётности эмитента в базе: {standards_badge} │ Отображается: **{chosen_basis}**")

                    # Live Market Snapshot from MOEX ISS
                    moex_snap = fetch_moex_market_snapshot(chosen_ticker)
                    last_price = moex_snap.get("price")
                    market_cap = moex_snap.get("market_cap")

                    # Extract key values for latest FY
                    fy_periods = [p for p in periods if p.endswith("-FY")]
                    latest_fy = fy_periods[-1] if fy_periods else (periods[-1] if periods else None)

                    net_income_row = next((r for r in rows if r["metric_code"] == "fin.net_income"), None)
                    roe_row = next((r for r in rows if r["metric_code"] == "calc.roe"), None)
                    net_debt_row = next((r for r in rows if r["metric_code"] == "calc.net_debt"), None)
                    assets_row = next((r for r in rows if r["metric_code"] in ("fin.total_assets", "fin.total_equity")), None)

                    # Top Multipliers Cards
                    c_m1, c_m2, c_m3, c_m4 = st.columns(4)

                    # 1. Price
                    if last_price:
                        chg = moex_snap.get("change_pct")
                        chg_str = f"{chg:+.2f}%" if chg is not None else None
                        c_m1.metric("Цена MOEX (TQBR)", f"{last_price:,.2f} ₽", delta=chg_str)
                    elif not tech_data.empty and chosen_ticker in tech_data["ticker"].values:
                        c_prices = tech_data.loc[tech_data["ticker"] == chosen_ticker, "Price"].dropna()
                        if not c_prices.empty:
                            c_m1.metric("Цена MOEX", f"{float(c_prices.iloc[-1]):,.2f} ₽")
                        else:
                            c_m1.metric("Цена MOEX", "Н/Д")
                    else:
                        c_m1.metric("Цена MOEX", "Н/Д")

                    # 2. Market Cap
                    if market_cap:
                        c_m2.metric("Капитализация", f"{market_cap / 1_000_000_000:,.1f} млрд ₽")
                    else:
                        c_m2.metric("Капитализация", "Н/Д")

                    # 3. P/E Multiplier
                    if latest_fy and net_income_row:
                        ni_val = net_income_row["values"].get(latest_fy)
                        if market_cap and ni_val and ni_val > 0:
                            pe_val = market_cap / ni_val
                            c_m3.metric(f"P/E ({latest_fy})", f"{pe_val:.2f}x")
                        elif ni_val is not None and ni_val <= 0:
                            c_m3.metric(f"P/E ({latest_fy})", "Убыток")
                        else:
                            c_m3.metric(f"P/E ({latest_fy})", "Н/Д")
                    else:
                        c_m3.metric("P/E", "Н/Д")

                    # 4. ROE or Debt
                    if latest_fy and roe_row and roe_row["values"].get(latest_fy) is not None:
                        roe_val = roe_row["values"].get(latest_fy)
                        c_m4.metric(f"ROE ({latest_fy})", f"{roe_val:.1f}%")
                    elif not is_bank and latest_fy and net_debt_row and net_debt_row["values"].get(latest_fy) is not None:
                        nd_val = net_debt_row["values"].get(latest_fy)
                        c_m4.metric(f"Чистый долг ({latest_fy})", f"{nd_val / 1_000_000_000:,.1f} млрд ₽")
                    elif is_bank and latest_fy and assets_row and assets_row["values"].get(latest_fy) is not None:
                        ass_val = assets_row["values"].get(latest_fy)
                        c_m4.metric(f"Активы ({latest_fy})", f"{ass_val / 1_000_000_000:,.1f} млрд ₽")
                    else:
                        c_m4.metric("ROE / Долг", "Н/Д")

                    st.markdown("---")

                    if periods and rows:
                        st.markdown(f"#### 📑 Финансовая отчётность по периодам ({chosen_basis})")
                        st.caption("Значения выражены в млрд ₽ (или %, где применимо). Значения `Н/Д` означают отсутствие публикации в данном периоде и никогда не заменяются нулём.")

                        table_data = []
                        for r in rows:
                            row_dict = {"Показатель": r["metric_name"]}
                            unit = r.get("unit", "RUB")
                            for p in periods:
                                v = r["values"].get(p)
                                if v is None:
                                    row_dict[p] = "Н/Д"
                                elif unit == "%":
                                    row_dict[p] = f"{v:.1f}%"
                                elif unit == "RUB":
                                    row_dict[p] = f"{v / 1_000_000_000:,.1f}"
                                else:
                                    row_dict[p] = f"{v:,.2f}"
                            table_data.append(row_dict)

                        df_matrix = pd.DataFrame(table_data)
                        st.dataframe(df_matrix, width="stretch", hide_index=True)

                        # Chart
                        st.markdown("#### 📈 График динамики показателей")
                        chartable_metrics = [
                            r["metric_name"] for r in rows 
                            if any(v is not None for v in r["values"].values())
                        ]
                        if chartable_metrics:
                            ch_m1, ch_m2 = st.columns([2, 3])
                            with ch_m1:
                                chosen_metric_name = st.selectbox(
                                    "Выберите показатель для графика:",
                                    options=chartable_metrics,
                                    key="foundry_chart_metric_sel"
                                )
                            chosen_row = next((r for r in rows if r["metric_name"] == chosen_metric_name), None)
                            if chosen_row:
                                chart_pts = []
                                u = chosen_row.get("unit", "RUB")
                                for p in periods:
                                    val = chosen_row["values"].get(p)
                                    if val is not None:
                                        chart_pts.append({
                                            "Период": p,
                                            "Значение": val / 1_000_000_000 if u == "RUB" else val,
                                            "Единица": "млрд ₽" if u == "RUB" else u
                                        })
                                if chart_pts:
                                    df_chart = pd.DataFrame(chart_pts)
                                    c_bars = alt.Chart(df_chart).mark_bar(size=36, color="#0288D1").encode(
                                        x=alt.X("Период:N", sort=periods, title="Период отчёта"),
                                        y=alt.Y("Значение:Q", title=f"{chosen_metric_name} ({df_chart['Единица'].iloc[0]})"),
                                        tooltip=["Период", alt.Tooltip("Значение:Q", format=",.1f"), "Единица"]
                                    ).properties(height=320)
                                    st.altair_chart(c_bars, width="stretch")

                        # Provenance and Sources Audit Expander
                        with st.expander("🔍 Аудит данных: Официальные источники и локаторы формул (get_evidence)", expanded=False):
                            st.markdown("Каждое число в таблице связано с официальным документом (МСФО/РСБУ), страницей и строкой публикации:")
                            evidence_records = []
                            for r in rows:
                                for p in periods:
                                    ev = r["evidence"].get(p)
                                    raw_item = r["raw_items"].get(p)
                                    val = r["values"].get(p)
                                    if val is not None:
                                        val_str = f"{val / 1_000_000_000:,.1f} млрд" if r.get("unit") == "RUB" else f"{val}"
                                        doc_title = ev.get("title") if ev else ("Методология / Расчётная метрика" if r.get("methodology") else "Официальная отчётность")
                                        locator_str = "—"
                                        if ev and ev.get("locator"):
                                            loc = ev["locator"]
                                            parts = []
                                            if loc.get("page"): parts.append(f"Стр. {loc['page']}")
                                            if loc.get("row"): parts.append(f"Строка {loc['row']}")
                                            if loc.get("table"): parts.append(f"Табл. {loc['table']}")
                                            locator_str = ", ".join(parts) if parts else str(loc)
                                        elif r.get("methodology"):
                                            locator_str = r["methodology"].get("formula", "Формула")

                                        evidence_records.append({
                                            "Показатель": r["metric_name"],
                                            "Период": p,
                                            "Значение": val_str,
                                            "Документ / Источник": doc_title,
                                            "Локатор (стр./строка)": locator_str,
                                            "Стандарт": raw_item.get("accounting_basis", chosen_basis) if raw_item else chosen_basis,
                                        })

                            if evidence_records:
                                st.dataframe(pd.DataFrame(evidence_records), width="stretch", hide_index=True)
                            else:
                                st.write("Сведения об источниках формируются...")
                    else:
                        st.info(f"Для эмитента {chosen_ticker} по стандарту {chosen_basis} пока нет загруженных периодов.")
                        if "IFRS" not in avail_standards and "RAS" in avail_standards:
                            st.info("💡 В базе данных доступны отчёты по стандарту РСБУ (RAS). Переключите радиокнопку стандарта выше.")


        with sub_screener:
            with st.spinner("Загрузка котировок и динамики рынка (1D, 1W, 1M, 3M, YTD)..."):
                screener_market_df = fetch_market_screener_data()
                commodities_data = fetch_commodities_barometer()
            
            if not screener_market_df.empty:
                render_market_view_component(
                    screener_market_df,
                    commodities_data,
                    my_portfolio_tickers=portfolio_tickers_list if my_portfolio else PORTFOLIO_TICKERS
                )
            else:
                st.warning("Не удалось загрузить котировки рынка с MOEX.")
