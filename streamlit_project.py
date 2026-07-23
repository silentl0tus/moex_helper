import os
from datetime import datetime, timedelta
from io import StringIO
from pathlib import Path

import pandas as pd
import requests
import streamlit as st
from moexalgo import Ticker

# ==========================================
# 1. СИСТЕМНЫЕ НАСТРОЙКИ
# ==========================================
st.set_page_config(layout="wide", page_title="MOEX Portfolio Intelligence")
st.title("🎯 Дашборд выбора активов для длинных стратегий на MOEX")
st.caption("Гибрид: цены с MOEX, фундаментал, правила риска под ваш портфель")

FALLBACK_TICKERS = ["SBER", "LKOH", "GAZP", "YDEX"]
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
    combined_df = pd.DataFrame()
    end_date = datetime.now().date()
    start_date = end_date - timedelta(days=120)

    for ticker in ticker_list:
        try:
            asset = Ticker(ticker)
            candles_df = _fetch_candles(asset, start_date, end_date)
            if candles_df.empty or "close" not in candles_df.columns:
                continue

            df = candles_df[["close"]].copy()
            if "begin" in candles_df.columns:
                df.index = pd.to_datetime(candles_df["begin"])
                df = df[["close"]]
            else:
                df.index = pd.to_datetime(df.index)

            combined_df[ticker] = df["close"].astype(float)
        except Exception as exc:
            st.sidebar.warning(f"Не удалось получить котировки для {ticker}: {exc}")

    return combined_df.dropna()

@st.cache_data(ttl=86400)
def fetch_moex_tickers():
    url = "https://iss.moex.com/iss/engines/stock/markets/shares/boards/TQBR/securities.json"
    params = {
        "iss.meta": "off",
        "iss.only": "securities",
        "securities.columns": "SECID,LISTLEVEL",
    }
    response = requests.get(url, params=params, timeout=30)
    response.raise_for_status()
    data = response.json()
    return sorted(
        row[0]
        for row in data["securities"]["data"]
        if row[1] in (1, 2)
    )

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
    return context

@st.cache_data(ttl=86400)
def fetch_smartlab_fundamentals():
    # Заглушка: сюда возвращаем логику парсинга фундаментала 
    # (либо через твой smartlab_probe, либо через DataHub)
    # Для теста системы возвращаем статические данные
    return pd.DataFrame({
        "ticker": ["SBER", "LKOH", "GAZP", "YDEX"],
        "P_E": [4.5, 6.2, 12.0, 30.0],
        "ROE_%": [22.0, 18.5, 3.0, 15.0],
        "Debt_EBITDA": [1.5, 0.5, 5.0, 1.2]
    })

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
    moex_tickers = fetch_moex_tickers()
    st.caption(f"MOEX TQBR, 1–2 эшелон: {len(moex_tickers)} тикеров")
    default_tickers = [t for t in FALLBACK_TICKERS if t in moex_tickers] or moex_tickers[:4]
    use_all_tickers = st.checkbox("Анализировать все тикеры", value=False)
    if use_all_tickers:
        selected_tickers = moex_tickers
        st.info(f"Выбрано {len(selected_tickers)} тикеров — загрузка может занять несколько минут.")
    else:
        selected_tickers = st.multiselect(
            "Тикеры для анализа",
            options=moex_tickers,
            default=default_tickers,
        )
    capital = st.number_input("Размер капитала, ₽", min_value=100000, value=1000000, step=100000)
    max_single_name = st.slider("Макс. доля одной акции", 0.05, 0.15, 0.12, 0.01)
    rest_cap = st.slider("Макс. доля остальных акций", 0.03, 0.05, 0.05, 0.01)

with st.spinner("Считываю сигналы систем..."):
    live_data = fetch_live_prices(selected_tickers)
    market_context = fetch_market_context()
    raw_fundamental_data = fetch_smartlab_fundamentals()

index_level = market_context.get("IMOEX")
usd_rate = market_context.get("USD000UTSTOM")
rules = build_portfolio_rules(index_level, usd_rate)

with st.expander(f"Полный список тикеров MOEX ({len(moex_tickers)})"):
    st.dataframe(
        pd.DataFrame({"ticker": moex_tickers}),
        use_container_width=True,
        hide_index=True,
    )

if not live_data.empty:
    cols = st.columns(4)
    cols[0].metric("IMOEX", f"{index_level:,.0f}" if index_level else "Н/Д")
    cols[1].metric("USD/RUB", f"{usd_rate:.2f}" if usd_rate else "Н/Д")
    cols[2].metric("Кэш", f"{rules['cash_target'] * 100:.0f}%")
    cols[3].metric("Облигации", f"{rules['bond_target'] * 100:.0f}%")
    st.info(f"{rules['regime']} | Облигации: {rules['bond_currency']}")
    st.line_chart((live_data / live_data.iloc[0] - 1) * 100)

st.markdown("---")
st.subheader("Фундаментальные мультипликаторы и Отбраковка")

if not raw_fundamental_data.empty:
    df_fund = raw_fundamental_data[raw_fundamental_data["ticker"].isin([t.upper() for t in selected_tickers])].copy()

    # ВРЕЗКА: Аварийный клапан защиты
    MIN_ROE = 5.0
    MAX_DEBT_EBITDA = 4.0
    
    df_fund["ROE_%"] = df_fund["ROE_%"].fillna(0)
    df_fund["Debt_EBITDA"] = df_fund["Debt_EBITDA"].fillna(999)

    management_filter = (df_fund['ROE_%'] >= MIN_ROE) & (df_fund['Debt_EBITDA'] <= MAX_DEBT_EBITDA)
    
    dropped_tickers = set(df_fund['ticker']) - set(df_fund[management_filter]['ticker'])
    if dropped_tickers:
        st.warning(f"⚠️ Сработала защита: компании с плохим управлением удалены: {', '.join(dropped_tickers)}")
        
    df_fund = df_fund[management_filter].copy()

    if not df_fund.empty:
        df_fund["Health_Score"] = ((df_fund["ROE_%"] / df_fund["P_E"]) / (df_fund["Debt_EBITDA"] + 0.1)).round(2)
        df_ranked = df_fund.sort_values(by=["Health_Score"], ascending=False)

        col1, col2 = st.columns([1.2, 0.8])
        col1.bar_chart(data=df_ranked, x="ticker", y="Health_Score")
        col2.dataframe(df_ranked[["ticker", "Health_Score", "ROE_%", "P_E", "Debt_EBITDA"]], use_container_width=True, hide_index=True)
            
        st.subheader("Рекомендуемые веса в портфеле")
        position_df = build_position_weights(df_ranked, rules["equity_target"], max_single=max_single_name, rest_cap=rest_cap)
        position_df["target_value_rub"] = (position_df["weight"] * capital).round(2)
        st.dataframe(position_df, use_container_width=True, hide_index=True)
    else:
        st.error("Аварийная остановка: Ни один актив не прошел проверку качества.")