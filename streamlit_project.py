import os
from datetime import datetime, timedelta
from io import StringIO
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor

import pandas as pd
import requests
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

MIN_DAILY_TURNOVER_RUB = 50_000_000
MOEX_TQBR_URL = "https://iss.moex.com/iss/engines/stock/markets/shares/boards/TQBR/securities.json"
REQUIRED_FUNDAMENTALS = ["ROE_%", "P_E", "Debt_EBITDA"]

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
        import re
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
        import re
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
        
    # Парсинг котировок металлов с Trading Economics (Золото, Сталь)
    try:
        import pandas as pd
        tables = pd.read_html("https://tradingeconomics.com/commodities", storage_options={'User-Agent': 'Mozilla/5.0'})
        for t in tables:
            if 'Metals' in t.columns:
                for _, row in t.iterrows():
                    metal_name = str(row['Metals']).lower()
                    if 'gold' in metal_name:
                        context["GOLD"] = float(row['Price'])
                    elif 'steel' in metal_name:
                        context["STEEL"] = float(row['Price'])
                break
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
                    return {"ticker": ticker, "SMA_50": pd.NA, "SMA_200": pd.NA, "RSI": pd.NA, "Price": pd.NA}
                close = df['close']
                sma_50 = close.rolling(50).mean().iloc[-1]
                sma_200 = close.rolling(200).mean().iloc[-1] if len(df) >= 200 else pd.NA
                rsi = calculate_rsi(close).iloc[-1]
                price = close.iloc[-1]
                return {"ticker": ticker, "SMA_50": sma_50, "SMA_200": sma_200, "RSI": rsi, "Price": price}
        except Exception:
            pass
        return {"ticker": ticker, "SMA_50": pd.NA, "SMA_200": pd.NA, "RSI": pd.NA, "Price": pd.NA}

    with ThreadPoolExecutor(max_workers=10) as ex:
        results = list(ex.map(get_ticker_tech, tickers))
    return pd.DataFrame(results)

@st.cache_data(ttl=300)
def load_sentiment_data():
    import json
    from pathlib import Path
    sentiment_path = Path(__file__).parent / "sentiment.json"
    if sentiment_path.exists():
        try:
            with open(sentiment_path, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return {}
    return {}

@st.cache_data(ttl=86400)
def fetch_smartlab_fundamentals(ticker_list):
    fundamental_data = []
    
    SMARTLAB_MAP = {
        'YDEX': 'YNDX',
        'SBER': 'SBER',
        'LKOH': 'LKOH',
        'GAZP': 'GAZP'
    }
    
    headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"}
    
    for ticker in ticker_list:
        try:
            smartlab_ticker = SMARTLAB_MAP.get(ticker.upper(), ticker.upper())
            url = f"https://smart-lab.ru/q/{smartlab_ticker}/f/y/"
            response = requests.get(url, headers=headers, timeout=10)
            
            tables = pd.read_html(StringIO(response.text))
            if not tables:
                continue
                
            df = tables[0]
            
            # Удаляем колонку LTM, так как смарт-лаб часто отдает по ней искаженные
            # или сломанные экстраполяции (из-за чего P/E бывает -700+).
            # Будем полагаться только на закрытые годовые отчеты.
            cols_to_drop = [col for col in df.columns if df[col].astype(str).str.contains('LTM', case=False).any()]
            if cols_to_drop:
                df = df.drop(columns=cols_to_drop)
                
            df = df.rename(columns={df.columns[0]: 'Metric'})
            df = df[[c for c in df.columns if c != '?']]
            
            for col in df.columns:
                if col != 'Metric':
                    df[col] = df[col].astype(str).str.replace(r'[\s%]', '', regex=True)
            
            # Удаляем дубликаты метрик, чтобы при транспонировании не было одинаковых колонок
            df = df.drop_duplicates(subset=['Metric'], keep='first')
            
            df = df.set_index('Metric').T
            
            for col in df.columns:
                df[col] = pd.to_numeric(df[col], errors='coerce')
                
            columns_map = {str(col).lower(): col for col in df.columns}
            
            roe_col = next((v for k, v in columns_map.items() if 'roe' in k), None)
            pe_col = next((v for k, v in columns_map.items() if 'p/e' in k or 'p / e' in k), None)
            debt_ebitda_col = next((v for k, v in columns_map.items() if 'долг/ebitda' in k or 'debt/ebitda' in k), None)
            rev_col = next((v for k, v in columns_map.items() if 'выручка' in k or 'чист. операц' in k or 'чистый операц' in k), None)
            pbv_col = next((v for k, v in columns_map.items() if 'p/bv' in k or 'p / bv' in k), None)
            fcf_yield_col = next((v for k, v in columns_map.items() if 'доходность fcf' in k), None)
            div_rub_col = next((v for k, v in columns_map.items() if 'дивиденд, руб' in k and 'ап' not in k), None)
            
            payload = {"ticker": ticker.upper()}
            if roe_col and not df[roe_col].dropna().empty:
                payload["ROE_%"] = df[roe_col].dropna().iloc[-1]
            if pe_col and not df[pe_col].dropna().empty:
                payload["P_E"] = df[pe_col].dropna().iloc[-1]
            if pbv_col and not df[pbv_col].dropna().empty:
                payload["P_BV"] = df[pbv_col].dropna().iloc[-1]
            if fcf_yield_col and not df[fcf_yield_col].dropna().empty:
                payload["FCF_Yield_%"] = df[fcf_yield_col].dropna().iloc[-1]
            if div_rub_col and not df[div_rub_col].dropna().empty:
                payload["Div_RUB"] = df[div_rub_col].dropna().iloc[-1]
                
            if rev_col and not df[rev_col].dropna().empty:
                rev_series = df[rev_col].dropna()
                if len(rev_series) >= 2:
                    current_rev = rev_series.iloc[-1]
                    prev_rev = rev_series.iloc[-2]
                    if prev_rev != 0:
                        payload["Rev_Growth_%"] = round((current_rev - prev_rev) / abs(prev_rev) * 100, 2)
                
            if debt_ebitda_col and not df[debt_ebitda_col].dropna().empty:
                payload["Debt_EBITDA"] = df[debt_ebitda_col].dropna().iloc[-1]
            elif ticker.upper() in ['SBER', 'SBERP', 'VTBR', 'TCSG', 'BSPB', 'CBOM', 'T', 'SVCB']: 
                # Для банков нет Debt/EBITDA, ставим безопасное значение
                payload["Debt_EBITDA"] = 1.0
            elif ticker.upper() in ['SNGS', 'SNGSP']:
                # У Сургутнефтегаза гигантская кэш-кубышка и отрицательный чистый долг
                payload["Debt_EBITDA"] = 0.0
                
            fundamental_data.append(payload)
            
        except Exception:
            pass
            
    df = pd.DataFrame(fundamental_data)
    if df.empty:
        return pd.DataFrame(columns=["ticker", "P_E", "ROE_%", "Debt_EBITDA", "Rev_Growth_%", "P_BV", "FCF_Yield_%", "Div_RUB"])
    return df

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

def build_position_weights(ranked_df, equity_target, max_single=0.15, rest_cap=0.05):
    if ranked_df.empty:
        return pd.DataFrame(columns=["ticker", "weight"])
    weights = [max_single if idx < 3 else rest_cap for idx, _ in ranked_df.iterrows()]
    scale = min(1.0, equity_target / sum(weights))
    
    ranked_df = ranked_df.copy()
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
            import json
            data = json.load(uploaded_file)
            assets = {a['id']: a['symbol'] for a in data.get('assets', [])}
            
            for t in data.get('trades', []):
                aid = t.get('asset')
                count = t.get('count', 0)
                if aid is None or count == 0: continue
                
                sym = assets.get(aid)
                if not sym: continue
                    
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
            if uploaded_file.name.endswith(".csv"):
                df_upload = pd.read_csv(uploaded_file)
            else:
                try:
                    df_upload = pd.read_excel(uploaded_file, sheet_name="Портфель")
                except ValueError:
                    df_upload = pd.read_excel(uploaded_file)
            
            df_upload.columns = [str(c).strip().lower() for c in df_upload.columns]
            ticker_col = next((c for c in df_upload.columns if c in ['тикер', 'ticker', 'акция', 'инструмент']), None)
            count_col = next((c for c in df_upload.columns if c in ['количество', 'кол-во', 'лоты', 'позиция', 'штук', 'qty', 'quantity', 'count']), None)
            price_col = next((c for c in df_upload.columns if c in ['средняя цена', 'цена покупки', 'avg price', 'price', 'цена']), None)
            
            if not ticker_col or not count_col:
                st.error("В таблице не найдены колонки 'Тикер' и 'Количество' (или похожие).")
            else:
                for _, row in df_upload.iterrows():
                    sym = str(row[ticker_col]).strip().upper()
                    if not sym or sym == 'NAN': continue
                    
                    try:
                        count = float(row[count_col])
                    except:
                        continue
                    if count <= 0: continue
                    
                    try:
                        price = float(row[price_col]) if price_col else 0.0
                    except:
                        price = 0.0
                        
                    invested = count * price
                    
                    if sym in moex_tickers:
                        target_dict = my_portfolio
                    elif sym.startswith('FX') or sym in ['RUSE', 'RSHE']:
                        target_dict = my_blocked
                    else:
                        target_dict = my_reserves
                        
                    if sym not in target_dict:
                        target_dict[sym] = {'count': 0, 'invested': 0.0}
                    
                    target_dict[sym]['count'] += count
                    target_dict[sym]['invested'] += invested
                    
        # Фильтруем закрытые позиции
        my_portfolio = {k: v for k, v in my_portfolio.items() if v['count'] > 0.01}
        my_reserves = {k: v for k, v in my_reserves.items() if v['count'] > 0.01}
        my_blocked = {k: v for k, v in my_blocked.items() if v['count'] > 0.01}
        
        # Считаем сумму в резервах (ОФЗ, фонды, валюта)
        reserves_total = sum(v['invested'] for v in my_reserves.values())
        blocked_total = sum(v['invested'] for v in my_blocked.values())
        
        my_reserves_invested = reserves_total + cash_rub
        my_blocked_invested = blocked_total
        
    if my_portfolio:
        portfolio_tickers_list = list(my_portfolio.keys())
        st.success(f"Загружено {len(portfolio_tickers_list)} акций из портфеля")
        if my_reserves_invested > 0:
            st.info(f"💵 Свободный Кэш и Облигации: {my_reserves_invested:,.0f} ₽")
            with st.expander("Детализация резервов"):
                st.write(f"**Прямой кэш (RUB):** {cash_rub:,.0f} ₽")
                for k, v in my_reserves.items():
                    st.write(f"**{k}**: {v['invested']:,.0f} ₽ (Позиция: {v['count']})")
        if my_blocked_invested > 0:
            st.warning(f"🔒 Заблокированные фонды (FinEx/Иностранные): {my_blocked_invested:,.0f} ₽")
    else:
        portfolio_tickers_list = PORTFOLIO_TICKERS
        
    st.markdown("---")
    
    st.header("Инвестиционные Часы 🕰️")
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
    
    st.markdown("---")
    st.subheader("Фильтры отбраковки")
    capital = st.number_input("Размер капитала, ₽", min_value=100000, value=4200000, step=100000)
    max_single_name = st.slider("Макс. доля одной акции", 0.05, 0.15, 0.12, 0.01)
    rest_cap = st.slider("Макс. доля остальных акций", 0.03, 0.05, 0.05, 0.01)

    st.markdown("---")
    st.subheader("Фильтры отбраковки")
    min_roe_filter = st.slider("Мин. ROE (%)", -50.0, 30.0, 5.0, 1.0, help="Компании с ROE ниже этого значения будут удалены.")
    max_debt_filter = st.slider("Макс. Долг/EBITDA", 0.0, 20.0, 4.0, 0.5, help="Компании с Долг/EBITDA выше этого значения будут удалены.")

with st.spinner("Считываю сигналы систем..."):
    live_data = fetch_live_prices(selected_tickers)
    market_context = fetch_market_context()
    tech_data = fetch_technical_indicators(selected_tickers)
    raw_fundamental_data = fetch_smartlab_fundamentals(selected_tickers)
    sentiment_data = load_sentiment_data()

index_level = market_context.get("IMOEX")
usd_rate = market_context.get("USD000UTSTOM")
rules = build_portfolio_rules(index_level, usd_rate)

with st.expander(f"Ликвидные тикеры MOEX ({len(moex_tickers)})"):
    st.dataframe(
        moex_universe[["ticker", "list_level", "turnover_mln"]].rename(
            columns={
                "ticker": "Тикер",
                "list_level": "Эшелон",
                "turnover_mln": "Оборот сегодня, млн ₽",
            }
        ),
        use_container_width=True,
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
    cols[6].metric("Сталь(CNY)", f"¥{steel_price:,.0f}" if steel_price else "Н/Д")
    
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

if not raw_fundamental_data.empty:
    df_fund = raw_fundamental_data[raw_fundamental_data["ticker"].isin([t.upper() for t in selected_tickers])].copy()

    # ВРЕЗКА: Аварийный клапан защиты (теперь берем из сайдбара)
    MIN_ROE = min_roe_filter
    MAX_DEBT_EBITDA = max_debt_filter
    
    df_fund["ROE_%"] = df_fund["ROE_%"].fillna(0)
    df_fund["Debt_EBITDA"] = df_fund["Debt_EBITDA"].fillna(999)

    # IT-сектор, для которого классический ROE не работает корректно
    HOLDING_TICKERS = ['AFKS', 'SFI', 'CBOM', 'GAZP'] # GAZP оцениваем как холдинг
    BANK_TICKERS = ['SBER', 'SBERP', 'VTBR', 'TCSG', 'BSPB', 'CBOM', 'SVCB', 'T']
    IT_TICKERS = ['ASTR', 'POSI', 'DIAS', 'DATA', 'SOFL', 'VKCO', 'YNDX', 'HEAD', 'OZON']
    CONSUMER_TICKERS = ['MGNT', 'FIVE', 'FIXP', 'OBUV', 'ORUP', 'BELU', 'AQUA']
    TELECOM_TICKERS = ['MTSS', 'RTKM', 'RTKMP']
    STEEL_TICKERS = ['CHMF', 'NLMK', 'MAGN']
    GOLD_TICKERS = ['PLZL', 'UGC', 'SELG']
    OIL_TICKERS = ['ROSN', 'LKOH', 'SIBN', 'TATN', 'TATNP', 'SNGS', 'SNGSP', 'TRNFP', 'BANE', 'BANEP', 'RNFT']
    UTILITIES_TICKERS = ['IRAO', 'UPRO', 'HYDR', 'MSNG', 'FEES', 'LSNG', 'LSNGP']
    
    is_portfolio = df_fund['ticker'].isin(portfolio_tickers_list)
    is_it = df_fund['ticker'].isin(IT_TICKERS)
    
    # Черный список: предбанкроты, уход с биржи, отвратительное корп. управление, дыры в капитале (скрытые убытки)
    TOXIC_TICKERS = ['PIKK', 'SMLT', 'EUTR', 'QIWI', 'POLY', 'ORUP', 'OBUV', 'RUGR', 'FIXP', 'CBOM']
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
        
        # Используем ROE_norm вместо сырого ROE_% и умножаем на мультипликатор роста
        df_fund["Health_Score"] = (((df_fund["ROE_norm"] / df_fund["P_E"]) / (1 + df_fund["Debt_EBITDA"])) * growth_multiplier).round(2)
        
        # Специфика Сургутнефтегаза и Холдингов: их P/E искажен переоценками кубышки/дочек. Оцениваем по P/BV.
        # GAZP добавлен сюда как холдинг (владеет Газпром нефтью, Газпромбанком), торгующийся глубоко ниже капитала.
        HOLDING_TICKERS = ['SNGS', 'SNGSP', 'AFKS', 'SFIN', 'ENPG', 'GAZP']
        is_holding = df_fund['ticker'].isin(HOLDING_TICKERS)
        df_fund.loc[is_holding, "Health_Score"] = (((3.0 / df_fund.loc[is_holding, "P_BV"].clip(lower=0.1)) / (1 + df_fund.loc[is_holding, "Debt_EBITDA"])) * growth_multiplier[is_holding]).round(2)
        
        # Специфика Банков (Финансовый сектор): их оценивают по связке Капитала (P/BV) и Эффективности (ROE).
        # Умножаем P_BV на 5.0, чтобы шкала оценки банка математически совпадала со шкалой P/E обычных компаний.
        BANK_TICKERS = ['SBER', 'SBERP', 'VTBR', 'TCSG', 'BSPB', 'CBOM', 'T', 'SVCB']
        is_bank = df_fund['ticker'].isin(BANK_TICKERS)
        df_fund.loc[is_bank, "Health_Score"] = (((df_fund.loc[is_bank, "ROE_norm"] / (df_fund.loc[is_bank, "P_BV"].clip(lower=0.1) * 5.0)) / (1 + df_fund.loc[is_bank, "Debt_EBITDA"])) * growth_multiplier[is_bank]).round(2)
        
        # Учет макро-контекста: корректировка нефтяников по текущей цене Urals
        urals_price = market_context.get("URALS")
        OIL_TICKERS = ['ROSN', 'LKOH', 'SIBN', 'TATN', 'TATNP', 'SNGS', 'SNGSP', 'TRNFP', 'BANE', 'BANEP', 'RNFT']
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
            if steel_price < 3200:
                steel_multiplier = 0.85 # Штраф: цикл стали на дне
            elif steel_price > 3800:
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
            df_fund['FCF_Yield_%'] = pd.NA
            
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
            return pd.NA
                
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
            data = sentiment_data.get(ticker)
            return data["score"] if data else 0.0
            
        def format_sentiment(score):
            if score > 0.1: return f"🟢 +{score:.2f}"
            elif score < -0.1: return f"🔴 {score:.2f}"
            else: return f"⚪ {score:.2f}"
            
        df_fund['Сентимент_Балл'] = df_fund['ticker'].apply(get_sentiment_score)
        df_fund['Сентимент'] = df_fund['Сентимент_Балл'].apply(format_sentiment)
        
        # Контрарианский подход: покупай на панике (бонус до +5% за негатив), продавай на эйфории (штраф до -5% за позитив)
        sentiment_multiplier = 1 - (df_fund['Сентимент_Балл'] * 0.05)
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
            growth = row.get('Rev_Growth_%', pd.NA)
            
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

        # 💼 АУДИТ ПОРТФЕЛЯ
        if my_portfolio:
            st.markdown("---")
            st.subheader("💼 Аудит моего портфеля")
            
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
            
        st.bar_chart(data=df_ranked, x="ticker", y="Health_Score")
        
        cols_to_show = ["ticker", "Health_Score", "Тренд", "RSI", "Сентимент", "Div_Yield_%", "Rev_Growth_%", "ROE_%", "P_E", "P_BV", "Debt_EBITDA"]
        if my_portfolio:
            cols_to_show.insert(2, "Доля в портфеле (%)")
            cols_to_show.insert(3, "PnL (%)")
            
        st.dataframe(
            df_ranked[cols_to_show], 
            use_container_width=True, 
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
            
        st.markdown("---")
        st.subheader("🗺️ Карта активов: Сравнение и балансировка")
        st.caption("По оси X — **Оценка (P/E)**: левее = дешевле. По оси Y — **Эффективность (ROE)**: выше = лучше. Размер точки пропорционален общему **Health Score**. Ваш портфель выделен отдельным цветом.")
        
        map_df = df_ranked.copy()
        map_df['Категория'] = map_df['ticker'].apply(lambda t: "Мой портфель" if t in PORTFOLIO_TICKERS else "Кандидаты с рынка")
        # Ограничиваем выбросы P/E для наглядности карты
        map_df['P/E (масштабированный)'] = map_df['P_E'].clip(lower=-40, upper=40)
        # Размер точки (только положительные значения)
        map_df['Здоровье'] = map_df['Health_Score'].clip(lower=0.1) * 10 
        
        import altair as alt
        
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

        st.markdown("---")
        st.subheader("Рекомендуемые веса в портфеле")
        position_df = build_position_weights(df_ranked, rules["equity_target"], max_single=max_single_name, rest_cap=rest_cap)
        position_df["target_value_rub"] = (position_df["weight"] * capital).astype(int)
        st.dataframe(position_df, use_container_width=True, hide_index=True)
    else:
        st.error("Аварийная остановка: Ни один актив не прошел проверку качества.")