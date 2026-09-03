import json
import os
import re
from datetime import datetime, timedelta
from io import StringIO
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor

import altair as alt
import pandas as pd
import requests
import yfinance as yf
import streamlit as st
st.set_page_config(page_title="Аналитика Портфеля", page_icon="📈", layout="wide")

from moexalgo import Ticker

PORTFOLIO_TICKERS = [
    "MGNT", "SBER", "ROSN", "NMTP", "SVCB",
    "T", "SIBN", "BELU", "CHMF", "NLMK",
    "SNGS", "TRNFP", "GAZP"
]

# ==========================================
# 1. СИСТЕМНЫЕ НАСТРОЙКИ
# ==========================================
st.title("🎯 Дашборд выбора активов для длинных стратегий на MOEX")
st.caption("Гибрид: цены с MOEX, фундаментал, правила риска под ваш портфель")

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
# Холдинги: P/E искажён переоценками дочек/кубышки — оцениваем по P/BV
HOLDING_TICKERS  = ['SNGS', 'SNGSP', 'AFKS', 'SFIN', 'ENPG', 'GAZP']
ZERO_DEBT_TICKERS = ['SNGS', 'SNGSP']  # отрицательный чистый долг
# Чёрный список: предбанкроты, уход с биржи, плохое корп. управление
TOXIC_TICKERS    = ['PIKK', 'SMLT', 'EUTR', 'QIWI', 'POLY', 'ORUP', 'OBUV', 'RUGR', 'FIXP', 'CBOM']

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

@st.cache_data(ttl=600)
def fetch_live_prices(ticker_list):
    end_date = datetime.now().date()
    start_date = end_date - timedelta(days=120)
    price_series = {}

    for ticker in ticker_list:
        try:
            asset = Ticker(ticker)
            candles_df = _fetch_candles(asset, start_date, end_date)
            if candles_df.empty or "close" not in candles_df.columns:
                continue

            series = candles_df["close"].astype(float)
            if "begin" in candles_df.columns:
                series.index = pd.to_datetime(candles_df["begin"])
            else:
                series.index = pd.to_datetime(series.index)
            price_series[ticker] = series
        except Exception as exc:
            st.sidebar.warning(f"Не удалось получить котировки для {ticker}: {exc}")

    if not price_series:
        return pd.DataFrame()

    return pd.DataFrame(price_series).sort_index().dropna(how="all")

def normalize_returns(price_df):
    return price_df.apply(
        lambda series: (series / series.dropna().iloc[0] - 1) * 100
        if series.notna().any()
        else series
    )

@st.cache_data(ttl=600)
def fetch_moex_universe(min_turnover_rub=MIN_DAILY_TURNOVER_RUB):
    params = {
        "iss.meta": "off",
        "iss.only": "securities,marketdata",
        "securities.columns": "SECID,LISTLEVEL",
        "marketdata.columns": "SECID,VALTODAY",
    }
    response = requests.get(MOEX_TQBR_URL, params=params, timeout=30)
    response.raise_for_status()
    data = response.json()

    turnover_by_ticker = {
        row[0]: row[1] or 0
        for row in data["marketdata"]["data"]
    }
    
    # Если максимальный оборот на всем рынке меньше порога, значит биржа закрыта или только открылась (выходной/утро)
    max_turnover = max(turnover_by_ticker.values()) if turnover_by_ticker else 0
    market_is_open = max_turnover > min_turnover_rub

    rows = []
    for ticker, list_level in data["securities"]["data"]:
        if list_level not in (1, 2) and ticker not in PORTFOLIO_TICKERS:
            continue
            
        turnover_rub = turnover_by_ticker.get(ticker, 0)
        
        # Если биржа открыта, жестко фильтруем по обороту. Иначе берем все акции 1-2 эшелона.
        if market_is_open and turnover_rub < min_turnover_rub and ticker not in PORTFOLIO_TICKERS:
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
    return df.sort_values("turnover_rub", ascending=False).reset_index(drop=True)

@st.cache_data(ttl=600)
def fetch_moex_tickers(min_turnover_rub=MIN_DAILY_TURNOVER_RUB):
    return fetch_moex_universe(min_turnover_rub=min_turnover_rub)["ticker"].tolist()

@st.cache_data(ttl=600)
def fetch_market_context():
    context = {}
    for symbol in ["IMOEX", "USD000UTSTOM"]:
        try:
            asset = Ticker(symbol)
            candles_df = _fetch_candles(asset, datetime.now().date() - timedelta(days=30), datetime.now().date())
            if not candles_df.empty and "close" in candles_df.columns:
                context[symbol] = float(candles_df["close"].iloc[-1])
        except Exception as exc:
            context[symbol] = None
            
    # Парсинг котировок Urals с tankermap
    try:
        url = "https://tankermap.com/market-data/urals"
        headers = {"User-Agent": "Mozilla/5.0"}
        response = requests.get(url, headers=headers, timeout=5)
        price_matches = re.findall(r'\$\s*(\d{2,3}\.\d{2})', response.text)
        if price_matches:
            context["URALS"] = float(price_matches[0])
        else:
            context["URALS"] = None
    except Exception:
        context["URALS"] = None
        
    # Парсинг Ключевой Ставки ЦБ РФ (Безрисковая ставка)
    try:
        url_cbr = "https://cbr.ru/hd_base/KeyRate/"
        headers = {"User-Agent": "Mozilla/5.0"}
        resp_cbr = requests.get(url_cbr, headers=headers, timeout=5)
        rate_match = re.search(r'<td>(\d{2}[,.]\d{2})</td>', resp_cbr.text)
        if rate_match:
            context["KEY_RATE"] = float(rate_match.group(1).replace(',', '.'))
        else:
            context["KEY_RATE"] = 16.0
    except Exception:
        context["KEY_RATE"] = 16.0
        
    # Парсинг официальной инфляции с главной ЦБ
    try:
        url_cbr_main = "https://cbr.ru/"
        resp_cbr_main = requests.get(url_cbr_main, headers=headers, timeout=5)
        inf_match = re.search(r'Инфляция.*?(\d{1,2}[,.]\d{1,2})\s*%', resp_cbr_main.text, re.IGNORECASE | re.DOTALL)
        if inf_match:
            official_inf = float(inf_match.group(1).replace(',', '.'))
        else:
            official_inf = 8.0
        context["INFLATION_OFFICIAL"] = official_inf
        context["INFLATION_REAL"] = official_inf + 4.0 # Премия недоверия Росстату
    except Exception:
        context["INFLATION_REAL"] = 12.0
        
    # Парсинг котировок сырья через yfinance (чтобы избежать блокировок Cloudflare)
    try:
        # Золото (COMEX Gold Futures)
        gold_ticker = yf.Ticker("GC=F")
        gold_df = gold_ticker.history(period="1d")
        if not gold_df.empty:
            context["GOLD"] = float(gold_df['Close'].iloc[-1])
            
        # Используем HRC (Hot-Rolled Coil US) в долларах США
        steel_ticker = yf.Ticker("HRC=F")
        steel_df = steel_ticker.history(period="1d")
        if not steel_df.empty:
            context["STEEL"] = float(steel_df['Close'].iloc[-1])
    except Exception:
        pass
        
    return context

@st.cache_data(ttl=3600)
def fetch_technical_indicators(tickers):
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
            resp = requests.get(url, params=params, timeout=5)
            data = resp.json()
            if 'candles' in data and data['candles']['data']:
                df = pd.DataFrame(data['candles']['data'], columns=data['candles']['columns'])
                if len(df) < 50:
                    return {"ticker": ticker, "SMA_50": float('nan'), "SMA_200": float('nan'), "RSI": float('nan'), "Price": float('nan')}
                close = df['close']
                sma_50 = close.rolling(50).mean().iloc[-1]
                sma_200 = close.rolling(200).mean().iloc[-1] if len(df) >= 200 else float('nan')
                rsi = calculate_rsi(close).iloc[-1]
                price = close.iloc[-1]
                return {"ticker": ticker, "SMA_50": sma_50, "SMA_200": sma_200, "RSI": rsi, "Price": price}
        except Exception:
            pass
        return {"ticker": ticker, "SMA_50": float('nan'), "SMA_200": float('nan'), "RSI": float('nan'), "Price": float('nan')}

    with ThreadPoolExecutor(max_workers=10) as ex:
        results = list(ex.map(get_ticker_tech, tickers))
    return pd.DataFrame(results)

@st.cache_data(ttl=600)
def fetch_bond_prices_moex():
    """
    Одним запросом тянет текущие цены и номиналы всех облигаций с MOEX ISS.
    Возвращает dict: {SECID: {'price': float, 'facevalue': float, 'accrued': float}}
    """
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
        ("stock", "bonds", "TQCB"),   # корпоративные
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
            
        st.error(f"Sentiment file not found! Tried: {paths_to_try}")
        return {}
        return {}
    try:
        with open(sentiment_path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
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

# ==========================================
# 3. БИЗНЕС-ЛОГИКА И РАСЧЕТЫ
# ==========================================
def build_portfolio_rules(index_level, usd_rate):
    if index_level is None: index_level = 2600
    if usd_rate is None: usd_rate = 80

    if index_level <= 2200:
        cash_target, bond_target, regime = 0.10, 0.10, "Низкий индекс — покупаем акции"
    elif index_level <= 2900:
        cash_target, bond_target, regime = 0.20, 0.15, "Средний индекс — умеренное развертывание"
    else:
        cash_target, bond_target, regime = 0.50, 0.20, "Высокий индекс — защита капитала"

    bond_currency = "USD-облигации" if usd_rate <= 72 else "RUB-облигации" if usd_rate >= 88 else "смешанный вариант"
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
    moex_universe = fetch_moex_universe()
    moex_tickers = moex_universe["ticker"].tolist()
    st.caption(
        f"MOEX TQBR, 1–2 эшелон, оборот ≥ {MIN_DAILY_TURNOVER_RUB // 1_000_000} млн ₽: "
        f"{len(moex_tickers)} тикеров"
    )
    st.header("Мой Портфель")
    uploaded_file = st.file_uploader("Загрузить Портфель (JSON / Excel / CSV)", type=["json", "xlsx", "csv"])
    
    my_portfolio = {}
    my_reserves_invested = 0.0
    my_blocked_invested = 0.0
    cash_rub = 0.0
    
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
                    if count > 0:
                        cash_rub += abs(t.get('summa', 0))
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
                        target_dict[sym]['invested'] -= abs(count) * avg_p

            for cb in data.get('cash-balances', []):
                for cash_item in cb.get('cash', []):
                    if cash_item.get('currency') == 'RUB':
                        cash_rub += cash_item.get('value', 0)

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
                    df_upload = xl.parse("Портфель")
                    _trades_parsed = False

                # ── Вариант B: личный журнал сделок (лист «Сделки») ─────────────────
                elif "Сделки" in xl.sheet_names:
                    df_tr = xl.parse("Сделки")
                    df_tr.columns = [str(c).strip() for c in df_tr.columns]

                    t_col  = next((c for c in df_tr.columns if c.lower() in ["тикер", "ticker", "symbol"]), None)
                    op_col = next((c for c in df_tr.columns if c.lower() in ["операция", "operation"]), None)
                    ty_col = next((c for c in df_tr.columns if c.lower() == "тип"), None)
                    q_col  = next((c for c in df_tr.columns if c.lower() in ["количество", "qty", "кол-во", "кол."]), None)
                    s_col  = next((c for c in df_tr.columns if c.lower() in ["сумма", "sum", "summa"]), None)

                    if t_col and op_col and q_col:
                        net_qty      = {}
                        net_invested = {}
                        net_type     = {}

                        for _, row in df_tr.iterrows():
                            sym = str(row.get(t_col, "")).strip().upper()
                            op  = str(row.get(op_col, "")).strip().lower()
                            typ = str(row.get(ty_col, "")).strip().lower() if ty_col else ""
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

                            if is_buy:
                                net_qty[sym]      += qty_abs
                                net_invested[sym] += summa
                            else:  # sell
                                prev = net_qty[sym]
                                if prev > 0:
                                    avg_p = net_invested[sym] / prev
                                    net_invested[sym] -= qty_abs * avg_p
                                net_qty[sym] -= qty_abs

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
        portfolio_tickers_list = list(my_portfolio.keys())
        st.success(f"Загружено {len(portfolio_tickers_list)} акций из портфеля")
        if my_reserves_invested > 0:
            st.info(f"💵 Облигации / Резервы: {my_reserves_invested:,.0f} ₽")
            with st.expander("Детализация резервов"):
                if cash_rub > 0:
                    st.write(f"Кэш (RUB): **{cash_rub:,.0f} ₽**")
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
            st.warning(f"🔒 Заблокированные фонды (FinEx/Иностранные): {my_blocked_invested:,.0f} ₽")
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

with st.spinner("Считываю сигналы систем..."):
    live_data = fetch_live_prices(selected_tickers)
    market_context = fetch_market_context()
    tech_data = fetch_technical_indicators(selected_tickers)
    raw_fundamental_data = fetch_smartlab_fundamentals(selected_tickers)
    sentiment_data = load_sentiment_data(_cache_buster=_sentiment_mtime())


index_level = market_context.get("IMOEX")
usd_rate = market_context.get("USD000UTSTOM")
rules = build_portfolio_rules(index_level, usd_rate)


st.markdown("---")
d_col1, d_col2, d_col3 = st.columns(3)
d_col1.metric("Текущая фаза цикла", selected_phase.split(" ")[0])
d_col2.metric("Ключевая ставка ЦБ", f"{market_context.get('KEY_RATE', 'Н/Д')}%")
d_col3.metric("Индекс МосБиржи", f"{index_level:,.0f}" if index_level else "Н/Д")
st.markdown("---")

tab1, tab2, tab3, tab4 = st.tabs(["🏆 Рейтинг и Аналитика", "💼 Мой Портфель", "🗺️ Карта рынка", "⚖️ Ребалансировка"])

with tab1:
    with st.expander(f"Ликвидные тикеры MOEX ({len(moex_tickers)})"):
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

    if not live_data.empty:
        cols = st.columns(9)
        cols[0].metric("IMOEX", f"{index_level:,.0f}" if index_level else "Н/Д")
        cols[1].metric("USD/RUB", f"{usd_rate:.2f}" if usd_rate else "Н/Д")
        urals_price = market_context.get("URALS")
        cols[2].metric("Urals", f"${urals_price:.2f}" if urals_price else "Н/Д")
        key_rate = market_context.get("KEY_RATE")
        cols[3].metric("Ставка", f"{key_rate}%" if key_rate else "Н/Д")
    
        inflation_real = market_context.get("INFLATION_REAL")
        cols[4].metric("Инфляция(Р)", f"{inflation_real}%" if inflation_real else "Н/Д")
    
        gold_price = market_context.get("GOLD")
        cols[5].metric("Золото", f"${gold_price:,.0f}" if gold_price else "Н/Д")
    
        steel_price = market_context.get("STEEL")
        cols[6].metric("Сталь(HRC,$)", f"${steel_price:,.0f}" if steel_price else "Н/Д")
    
        cols[7].metric("Кэш", f"{rules['cash_target'] * 100:.0f}%")
        cols[8].metric("Облигации", f"{rules['bond_target'] * 100:.0f}%")
    
        st.markdown("---")
        if selected_phase.startswith("Рефляция"):
            st.info("🕰️ **Часы: Рефляция.** Ставки падают, экономика на спаде. Акции еще слабы, лидируют длинные облигации (ОФЗ) и защитные сектора (Телеком, Ритейл). Сырьевики под давлением.")
        elif selected_phase.startswith("Восстановление"):
            st.success("🕰️ **Часы: Восстановление.** Деньги дешевеют, экономика разгоняется. Идеальное время для акций Роста (IT) и Банков. Облигации продаем.")
        elif selected_phase.startswith("Перегрев"):
            st.warning("🕰️ **Часы: Перегрев.** Инфляция разгоняется, ЦБ повышает ставки. Лидирует сырье (Нефть, Металлы). Рост и IT страдают от стоимости денег.")
        elif selected_phase.startswith("Стагфляция"):
            st.error("🕰️ **Часы: Стагфляция.** Экономика падает, инфляция высокая. Спасает только Кэш (LQDT) и Золото. Бегите из акций роста и банков.")
    
        st.info(f"{rules['regime']} | Облигации: {rules['bond_currency']}")
        chart_data = normalize_returns(live_data)
        loaded_tickers = chart_data.columns[chart_data.notna().any()].tolist()
        st.caption(
            f"На графике: {len(loaded_tickers)} из {len(selected_tickers)} выбранных тикеров "
            f"(доходность от первой доступной котировки, %)"
        )
        st.line_chart(chart_data)
    elif selected_tickers:
        st.warning(
            f"Котировки не загружены для выбранных тикеров ({len(selected_tickers)} шт.). "
            "Проверьте предупреждения в sidebar."
        )
    else:
        st.info("Выберите хотя бы один тикер в sidebar, чтобы построить график.")

    st.markdown("---")
    st.subheader("Фундаментальные мультипликаторы и Отбраковка")

    with st.expander("ℹ️ Как рассчитывается Health Score (Алгоритм оценки)?"):
        st.markdown("""
        **Health Score** — это комплексный математический рейтинг, который показывает "здоровье" и инвестиционную привлекательность компании.
        Рейтинг начинается с базовой единицы (**1.0**) и умножается на ряд коэффициентов:
    
        1. **Рентабельность и Рост (Growth):**
           - `ROE > 15%` ➡️ бонус **+0.2** (Эффективный бизнес)
           - `ROE < 0%` ➡️ штраф **-0.5** (Убыточный бизнес)
           - `P/E < 8` ➡️ бонус **+0.2** (Недооценка)
           - `P/E > 15` ➡️ штраф **-0.3** (Переоценка)
           - `Рост Выручки > 10%` ➡️ бонус **+0.1**
           - `Рост Выручки < 0%` ➡️ штраф **-0.2** (Стагнация)
       
        2. **Дивидендная Безопасность (Dividends):**
           - Див. доходность `> 8%` ➡️ бонус **+0.3**
           - `FCF Yield > Div Yield` ➡️ бонус **+0.1** (Дивиденды выплачиваются из свободного кэша, а не в долг)
       
        3. **Долговая нагрузка и Риски (Risk):**
           - `Debt/EBITDA > 3` ➡️ штраф **-0.4** (Риск банкротства при жесткой ДКП ЦБ)
           - Токсичные тикеры (ЧС) ➡️ штраф **-0.3** (Проблемы с листингом или корп. управлением)
           - `P/BV < 0.5` ➡️ бонус **+0.1** (Торгуется ниже балансовой стоимости)
       
        4. **Инфляционный радар (Inflation):**
           - Если реальная див. доходность и реальный ROE отрицательные (ниже инфляции на 4%+) ➡️ жесткий штраф **-0.5**.
             *(Такие акции получают статус **"Сжигатель капитала ⚠️"** — бизнес приносит доходность сильно ниже инфляции, вы теряете реальную покупательную способность).*
           - Если реальная див. доходность обгоняет инфляцию ➡️ бонус **+0.1** (Статус **"Защитник капитала 🛡️"**).
       
        5. **Технический Анализ (Trend):**
           - Цена ниже `SMA-50` и `SMA-200` ➡️ штраф **-0.2**.
             *(Статус **"Падающий нож 🔪"** — попытка купить дно на падающем тренде может привести к двойному убытку).*
           - Цена выше `SMA-50`, но ниже `SMA-200` ➡️ бонус **+0.2** (Статус **"Восходящий тренд 🚀"**).
           - Перепроданность (`RSI < 30`) ➡️ бонус **+0.1**.
       
        6. **Настроения SmartLab (Sentiment):**
           - Сильный позитив (`Score > 30`) ➡️ бонус **+0.1**
           - Глубокий негатив (`Score < -10`) ➡️ штраф **-0.1**
       
        7. **Макро-Фаза (Macro Clock):**
           - Дополнительные ротационные бонусы `+0.2` и штрафы `-0.1` в зависимости от стадии Инвестиционных Часов (Рефляция, Перегрев и т.д.).
       
        *Акции с итоговым счетом **ниже 1.0** помечаются как "слабые" (Кандидаты на продажу). Лидеры рынка уходят выше 1.5.*
        """)

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
        # Нормализуем ROE для расчета Health Score, чтобы аномалии (500% или -1000%) не ломали вес в портфеле
        # Ограничиваем любой ROE сверху значением 40% (отличный бизнес)
        df_fund['ROE_norm'] = df_fund['ROE_%'].clip(upper=40.0)
        
        # Обновляем маску is_it для отфильтрованного датафрейма
        current_is_it = df_fund['ticker'].isin(IT_TICKERS)
        
        # Для IT-компаний, если ROE ушел в минус из-за бухгалтерского списания капитала,
        # присваиваем им "нормативный" успешный ROE = 30.0% для адекватного участия в рейтинге
        df_fund.loc[current_is_it & (df_fund['ROE_norm'] <= 0), 'ROE_norm'] = 30.0
        # Учет роста бизнеса (Growth Premium/Penalty)
        if 'Rev_Growth_%' not in df_fund.columns:
            df_fund['Rev_Growth_%'] = 0.0
        df_fund['Rev_Growth_%'] = df_fund['Rev_Growth_%'].fillna(0.0)
        
        if 'P_BV' not in df_fund.columns:
            df_fund['P_BV'] = 1.0
        df_fund['P_BV'] = df_fund['P_BV'].fillna(1.0)
        
        # Превращаем процент роста в мультипликатор: +20% роста = 1.2x к оценке здоровья, -15% = 0.85x.
        # Ограничиваем влияние выбросов (не больше удвоения скора и не меньше половинки).
        growth_multiplier = 1 + (df_fund['Rev_Growth_%'].clip(lower=-50, upper=100) / 100.0)
        
        # Ограничиваем бонус за отрицательный долг (максимум х2 к баллу), чтобы не ломать рейтинг
        safe_debt = df_fund["Debt_EBITDA"].clip(lower=-0.5)
        
        # Используем ROE_norm вместо сырого ROE_% и умножаем на мультипликатор роста
        df_fund["Health_Score"] = (((df_fund["ROE_norm"] / df_fund["P_E"]) / (1 + safe_debt)) * growth_multiplier).round(2)
        
        # Специфика Сургутнефтегаза и Холдингов: их P/E искажен переоценками кубышки/дочек. Оцениваем по P/BV.
        # GAZP добавлен сюда как холдинг (владеет Газпром нефтью, Газпромбанком), торгующийся глубоко ниже капитала.
        is_holding = df_fund['ticker'].isin(HOLDING_TICKERS)
        df_fund.loc[is_holding, "Health_Score"] = (((3.0 / df_fund.loc[is_holding, "P_BV"].clip(lower=0.1)) / (1 + safe_debt[is_holding])) * growth_multiplier[is_holding]).round(2)
        
        # Специфика Банков (Финансовый сектор): их оценивают по связке Капитала (P/BV) и Эффективности (ROE).
        # Умножаем P_BV на 5.0, чтобы шкала оценки банка математически совпадала со шкалой P/E обычных компаний.
        is_bank = df_fund['ticker'].isin(BANK_TICKERS)
        df_fund.loc[is_bank, "Health_Score"] = (((df_fund.loc[is_bank, "ROE_norm"] / (df_fund.loc[is_bank, "P_BV"].clip(lower=0.1) * 5.0)) / (1 + safe_debt[is_bank])) * growth_multiplier[is_bank]).round(2)
        
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
        
        # Расчет и учет Дивидендной доходности (Stock-picking подход)
        if 'Div_RUB' not in df_fund.columns:
            df_fund['Div_RUB'] = 0.0
            
        def get_current_price(ticker):
            try:
                # Если тикер не найден в live_data, вернем NaN
                if ticker in live_data.columns:
                    return live_data[ticker].dropna().iloc[-1]
            except Exception:
                pass
            return float('nan')
                
        df_fund['Div_RUB'] = df_fund['Div_RUB'].fillna(0.0)
        # Приводим к float, игнорируя текст (на смарт-лабе могут быть кривые данные)
        df_fund['Div_RUB'] = pd.to_numeric(df_fund['Div_RUB'], errors='coerce').fillna(0.0)
        df_fund['Current_Price'] = df_fund['ticker'].apply(get_current_price)
        df_fund['Div_Yield_%'] = (df_fund['Div_RUB'] / df_fund['Current_Price'] * 100).fillna(0.0).round(2)
        
        def get_div_multiplier(yield_val):
            if yield_val >= 9.0:
                return 1.20  # Огромный бонус за высокие дивиденды
            elif yield_val >= 5.0:
                return 1.10  # Средний бонус
            elif yield_val == 0.0:
                return 0.85  # Штраф -15% за "жлобство" (компания не делится деньгами)
            else:
                return 1.0
                
        div_multiplier = df_fund['Div_Yield_%'].apply(get_div_multiplier)
        
        # Убираем штраф за 0% дивов для IT компаний (они реинвестируют в мощный рост)
        is_it = df_fund['ticker'].isin(IT_TICKERS)
        div_multiplier[is_it & (df_fund['Div_Yield_%'] == 0.0)] = 1.0
        
        df_fund["Health_Score"] = (df_fund["Health_Score"] * div_multiplier).round(2)
            
        # Интеграция Sentiment Analysis (Настроения толпы)
        def get_sentiment_score(ticker):
            data = sentiment_data.get(str(ticker).upper().strip())
            return data["score"] if data else 0.0
            
        def format_sentiment(score):
            if score > 0.1: return f"🟢 +{score:.2f}"
            elif score < -0.1: return f"🔴 {score:.2f}"
            else: return f"⚪ {score:.2f}"
            
        df_fund['Сентимент_Балл'] = df_fund['ticker'].apply(get_sentiment_score)
        df_fund['Сентимент'] = df_fund['Сентимент_Балл'].apply(format_sentiment)
        
        # Прямой подход: позитивный сентимент дает бонус (до +5%), негативный - штраф (до -5%)
        sentiment_multiplier = 1 + (df_fund['Сентимент_Балл'] * 0.05)
        df_fund["Health_Score"] = (df_fund["Health_Score"] * sentiment_multiplier).round(2)
        
        # Интеграция Безрисковой Ставки (Key Rate / Cost of Money)
        key_rate_val = market_context.get("KEY_RATE", 16.0)
        
        def apply_rfr_penalty(row):
            score = row['Health_Score']
            ticker = row['ticker']
            
            # IT-сектор: растут быстрее ставки, оцениваются по мультипликаторам
            if ticker in IT_TICKERS: return score
            # Холдинги: E/P и ROE искажены кубышкой или дочками
            if ticker in HOLDING_TICKERS: return score
            
            # Цикличные компании (Металлурги, Майнеры): их прибыль волатильна. Покупать их на низком P/E (на пике цикла) опасно,
            # а высокий P/E (дно цикла) часто бывает лучшей точкой входа. Прощаем им низкий E/P, смотрим только на ROE.
            CYCLICAL_TICKERS = ['CHMF', 'NLMK', 'MAGN', 'ALRS', 'PLZL', 'UGC', 'MTLR', 'RASP', 'SELG']
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
            
            # Жесткий Сток-пикинг (-30% штраф): 
            # Если бизнес зарабатывает меньше банковского вклада, он сжигает акционерную стоимость
            if row['ROE_norm'] < key_rate_val or earnings_yield < key_rate_val:
                score = score * 0.7
                
            return round(score, 2)
            
        df_fund["Health_Score"] = df_fund.apply(apply_rfr_penalty, axis=1)
        
        # Слияние с техническим анализом
        df_fund = pd.merge(df_fund, tech_data, on="ticker", how="left")
        
        def apply_div_multiplier(row):
            score = row['Health_Score']
            div = row['Div_Yield_%']
            pe = row['P_E']
            growth = row.get('Rev_Growth_%', float('nan'))
            
            # Расчет Payout Ratio (Доля прибыли, идущая на дивиденды)
            # Earnings Yield = 100 / P/E. Значит Payout Ratio = Div_Yield / (100 / P_E) = Div_Yield * P_E / 100
            payout_ratio = 0
            if pd.notna(div) and div > 0 and pd.notna(pe) and pe > 0:
                payout_ratio = (div * pe) / 100
            
            if pd.isna(div) or div <= 0:
                if row['ticker'] not in IT_TICKERS:
                    return score * 0.85 # Штраф за жлобство (кроме IT)
                return score
                
            # ЗАЩИТА ОТ КВАЗИОБЛИГАЦИЙ:
            # 1. Компания платит дивидендов больше, чем зарабатывает (Payout > 100%). Проедает капитал в долг (как МТС).
            if payout_ratio > 1.0:
                return score * 0.8 # Штраф за проедание капитала
                
            # 2. Компания платит высокие дивы (>10%), но не растет (выручка < 5%). Это стагнирующая квазиоблигация.
            if div > 10 and (pd.isna(growth) or growth < 5):
                # Режем дивидендный бонус в два раза, так как нет развития бизнеса
                return score * (1 + (min(div, 20) / 200))
                
            # Здоровый баланс: компания платит дивиденды ИЗ ПРИБЫЛИ и при этом продолжает расти
            return score * (1 + (min(div, 20) / 100))
            
        df_fund["Health_Score"] = df_fund.apply(apply_div_multiplier, axis=1)
        
        # Защита от сжигания капитала (Инфляционный радар)
        inflation_real_val = market_context.get("INFLATION_REAL", 12.0)
        def apply_inflation_penalty(row):
            score = row['Health_Score']
            roe = row['ROE_norm']
            div = row['Div_Yield_%']
            growth = row.get('Rev_Growth_%', 0)
            if pd.isna(growth): growth = 0
            
            is_destroyer = False
            # Штраф за уничтожение капитала (ROE ниже реальной инфляции)
            if roe < inflation_real_val:
                score *= 0.7
                
            # Сжигатель покупательной способности
            if pd.notna(div) and div > 0:
                if div < inflation_real_val and growth < inflation_real_val:
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
            
        df_ranked = df_fund.sort_values(by=["Health_Score"], ascending=False)
        
        # Делаем RSI человекочитаемым
        def format_rsi(rsi_val):
            if pd.isna(rsi_val): return "Н/Д"
            if rsi_val >= 70: return f"{rsi_val:.1f} (🔥 Перегрев)"
            if rsi_val <= 30: return f"{rsi_val:.1f} (❄️ Перепродан)"
            return f"{rsi_val:.1f} (Норма)"
            
        df_ranked['RSI'] = df_ranked['RSI'].apply(format_rsi)

        with tab2:
            # 💼 АУДИТ ПОРТФЕЛЯ
            if my_portfolio:
            
                def get_port_count(ticker): return my_portfolio.get(ticker, {}).get('count', 0)
                def get_port_invested(ticker): return my_portfolio.get(ticker, {}).get('invested', 0)
                
                df_ranked['Лоты'] = df_ranked['ticker'].apply(get_port_count)
                df_ranked['Вложено'] = df_ranked['ticker'].apply(get_port_invested)
                df_ranked['Текущая Стоимость'] = df_ranked['Лоты'] * df_ranked['Price']
            
                port_mask = df_ranked['Лоты'] > 0
                df_port = df_ranked[port_mask].copy()
            
                total_val = df_port['Текущая Стоимость'].sum()
                total_inv = df_port['Вложено'].sum()
                pnl_rub = total_val - total_inv
                pnl_pct = (pnl_rub / total_inv * 100) if total_inv > 0 else 0
            
                port_health = (df_port['Health_Score'] * df_port['Текущая Стоимость']).sum() / total_val if total_val > 0 else 0
                
                pc1, pc2, pc3 = st.columns(3)
                pc1.metric("Стоимость акций (MOEX)", f"{total_val:,.0f} ₽")
                pc2.metric("Бумажный PnL", f"{pnl_rub:,.0f} ₽", f"{pnl_pct:.1f}%")
                pc3.metric("Индекс Здоровья (Beta)", f"{port_health:.2f}x", "Сильнее рынка" if port_health > 1.0 else "Слабее рынка")
                       
                st.markdown("#### 🤖 Рекомендации Робо-Эдвайзера")
                sells = df_port[df_port['Health_Score'] < 1.0]['ticker'].tolist()
                if sells:
                    st.error(f"**🔴 ПРОДАВАТЬ (Кандидаты на вылет):** {', '.join(sells)}. Эти бумаги фундаментально слабы и тянут портфель на дно.")
                else:
                    st.success("**🟢 Портфель очищен от мусора.** Кандидатов на срочную продажу нет.")
                
                buys = df_ranked[(~df_ranked['ticker'].isin(portfolio_tickers_list)) & (~df_ranked['ticker'].isin(TOXIC_TICKERS))].head(3)['ticker'].tolist()
                st.info(f"**🔵 ЦЕЛЕВЫЕ ПОКУПКИ (Кандидаты на добавление):** {', '.join(buys)}. Бумаги с высшим баллом, которых у вас еще нет.")
            
                df_ranked['Доля в портфеле (%)'] = (df_ranked['Текущая Стоимость'] / total_val * 100).fillna(0).round(1)
                df_ranked['PnL (%)'] = ((df_ranked['Текущая Стоимость'] - df_ranked['Вложено']) / df_ranked['Вложено'] * 100).fillna(0).round(1)
            
        with tab1:
            st.bar_chart(data=df_ranked, x="ticker", y="Health_Score")
        
            st.page_link("pages/2_💬_Сентимент_и_Пульс.py", label="Открыть детальную ленту сообщений и сентимента (Smart-Lab)", icon="💬")
        
            cols_to_show = ["ticker", "Health_Score", "Тренд", "RSI", "Сентимент", "Div_Yield_%", "Rev_Growth_%", "ROE_%", "P_E", "P_BV", "Debt_EBITDA"]
            if my_portfolio:
                cols_to_show.insert(2, "Доля в портфеле (%)")
                cols_to_show.insert(3, "PnL (%)")
            
            st.dataframe(
                df_ranked[cols_to_show], 
                width="stretch", 
                hide_index=True,
                column_config={
                    "Health_Score": st.column_config.NumberColumn(
                        "Health_Score",
                        help="Комплексный рейтинг здоровья бизнеса. База = 1.0. Умножается на коэффициенты за рентабельность, долг, дивиденды и тренд. Ниже 1.0 — кандидаты на продажу."
                    ),
                    "Тренд": st.column_config.TextColumn(
                        "Тренд",
                        help="🔪 Падающий нож (цена ниже SMA-50 и SMA-200).\n🚀 Восходящий тренд (пробой SMA-50).\nБоковик (нейтрально)."
                    ),
                    "Сентимент": st.column_config.TextColumn(
                        "Сентимент",
                        help="Настроения на SmartLab.\n🟢 Позитив (дает бонус)\n🔴 Негатив (штраф)"
                    ),
                    "Div_Yield_%": st.column_config.NumberColumn(
                        "Div_Yield_%",
                        help="⚠️ Сжигатель капитала: если дивиденды и реальный ROE отрицательные (ниже инфляции), компания жестко штрафуется."
                    ),
                    "Debt_EBITDA": st.column_config.NumberColumn(
                        "Debt_EBITDA",
                        help="Долговая нагрузка. Значение выше 3.0 — красный флаг риска банкротства."
                    )
                }
            )
            
        with tab3:
            st.caption("По оси X — **Оценка (P/E)**: левее = дешевле. По оси Y — **Эффективность (ROE)**: выше = лучше. Размер точки пропорционален общему **Health Score**. Ваш портфель выделен отдельным цветом.")
        
            map_df = df_ranked.copy()
            map_df['Категория'] = map_df['ticker'].apply(lambda t: "Мой портфель" if t in PORTFOLIO_TICKERS else "Кандидаты с рынка")
            # Ограничиваем выбросы P/E для наглядности карты
            map_df['P/E (масштабированный)'] = map_df['P_E'].clip(lower=-40, upper=40)
            # Размер точки (только положительные значения)
            map_df['Здоровье'] = map_df['Health_Score'].clip(lower=0.1) * 10 
        
            # Жестко задаем контрастные цвета: яркий красный для вашего портфеля, приглушенный синий для остальных
            domain = ['Мой портфель', 'Кандидаты с рынка']
            range_ = ['#FF3366', '#1E88E5'] 
        
            base = alt.Chart(map_df).encode(
                x=alt.X('P/E (масштабированный):Q', title='P/E (Оценка)'),
                y=alt.Y('ROE_%:Q', title='ROE (Эффективность)'),
                color=alt.Color('Категория:N', scale=alt.Scale(domain=domain, range=range_)),
                tooltip=['ticker', 'Health_Score', 'P_E', 'ROE_%', 'Категория']
            )
        
            points = base.mark_circle().encode(
                size=alt.Size('Здоровье:Q', legend=None)
            )
        
            text = base.mark_text(
                align='left',
                baseline='middle',
                dx=9,
                fontSize=11,
                fontWeight='bold'
            ).encode(
                text='ticker:N'
            )
        
            chart = (points + text).interactive()
            st.altair_chart(chart, use_container_width=True)

        with tab4:
            position_df = build_position_weights(
                df_ranked, rules["equity_target"],
                max_single=max_single_name, rest_cap=rest_cap, n_assets=n_assets
            )
            position_df["target_value_rub"] = (position_df["weight"] * capital).astype(int)
            st.caption(f"Топ-{n_assets} активов по Health Score | Акционерная доля: {rules['equity_target']*100:.0f}% от капитала")
            st.dataframe(position_df, width="stretch", hide_index=True)
    else:
        st.error("Аварийная остановка: Ни один актив не прошел проверку качества.")