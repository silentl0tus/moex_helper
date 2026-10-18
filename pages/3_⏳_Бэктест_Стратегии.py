"""Страница исторического бэктеста и стресс-тестирования портфеля на данных MOEX.

Позволяет симулировать поведение портфеля на реальных исторических котировках Московской биржи,
сравнивать результаты с Индексом МосБиржи (IMOEX) и безрисковой ставкой ЦБ РФ,
тестировать различные режимы ребалансировки (Buy & Hold, ежемесячно, ежеквартально)
и рассчитывать ключевые институциональные риск-метрики (Sharpe, Sortino, Calmar, Max Drawdown, Alpha, Beta).
"""

import sys
from datetime import datetime, timedelta
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import altair as alt
import numpy as np
import pandas as pd
import requests
import streamlit as st

st.set_page_config(
    page_title="Бэктест Портфеля MOEX | MOEX Helper",
    page_icon="⏳",
    layout="wide"
)

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
</style>
""", unsafe_allow_html=True)

try:
    from moexalgo import Ticker
except ImportError:
    Ticker = None

DEFAULT_PORTFOLIO_TICKERS = [
    "MGNT", "SBER", "ROSN", "NMTP", "LKOH",
    "T", "SIBN", "BELU", "CHMF", "NLMK",
    "SNGS", "TRNFP", "GAZP"
]

PREDECESSOR_MAP: Dict[str, str] = {
    "YDEX": "YNDX",
    "T": "TCSG",
    "HEAD": "HHRU"
}

POPULAR_LIQUID_TICKERS = [
    "SBER", "GAZP", "LKOH", "ROSN", "NVTK", "GMKN", "CHMF", "NLMK",
    "MAGN", "PLZL", "ALRS", "VTBR", "T", "SVCB", "BSPB", "MTSS",
    "MGNT", "SMLT", "SGZH", "AFLT", "RTKM", "PHOR", "TATN", "SIBN",
    "TRNFP", "FLOT", "AFKS", "SELG", "HEAD", "YDEX", "OZON", "BELU", "NMTP"
]


# ==========================================
# 0. ИСТОРИЧЕСКИЕ СОБЫТИЯ НА МОСКОВСКОЙ БИРЖЕ
# ==========================================

MOEX_HISTORICAL_EVENTS = [
    {
        "date": "2020-02-20",
        "title": "🦠 Начало COVID-19",
        "description": "Обвал мировых и российских рынков из-за пандемии коронавируса, падение нефти до отрицательных значений.",
        "color": "#E53935"
    },
    {
        "date": "2021-10-26",
        "title": "🏔️ Пик IMOEX (ATH 4292 п.)",
        "description": "Исторический максимум Индекса МосБиржи на волне сверхдоходов сырьевого сектора и притока частных инвесторов.",
        "color": "#43A047"
    },
    {
        "date": "2021-12-21",
        "title": "💼 Старт портфеля (21.12.2021)",
        "description": "Точка отсчета портфеля инвестора на izi.invest перед геополитическим кризисом 2022 года.",
        "color": "#1E88E5"
    },
    {
        "date": "2022-02-24",
        "title": "⚔️ Начало СВО (Стоп торгов)",
        "description": "Обвал рынка на 33% за один день. Остановка торгов акциями на Московской бирже на месяц (до 24 марта 2022).",
        "color": "#D32F2F"
    },
    {
        "date": "2022-03-24",
        "title": "🟢 Рестарт торгов MOEX",
        "description": "Возобновление торгов 33 наиболее ликвидными акциями с запретом коротких позиций и блокировкой нерезидентов.",
        "color": "#00897B"
    },
    {
        "date": "2022-09-21",
        "title": "📢 Мобилизация (Дно 1906 п.)",
        "description": "Объявление частичной мобилизации. Локальное дно IMOEX, с которого начался мощный двухлетний бычий тренд.",
        "color": "#FB8C00"
    },
    {
        "date": "2023-06-24",
        "title": "🛡️ События ЧВК Вагнер",
        "description": "Краткосрочный стресс выходного дня с быстрым выкупом просадки в понедельник.",
        "color": "#8E24AA"
    },
    {
        "date": "2023-08-15",
        "title": "🏦 Ставка ЦБ 12% (Старт ДКП)",
        "description": "Внеплановое заседание Банка России из-за курса доллара выше 100 ₽. Старт цикла рекордного ужесточения ДКП.",
        "color": "#FDD835"
    },
    {
        "date": "2024-06-12",
        "title": "🚫 Санкции против MOEX и НКЦ",
        "description": "Блокирующие санкции США (OFAC) против Московской биржи и НКЦ. Остановка биржевых торгов долларом США и евро.",
        "color": "#C2185B"
    },
    {
        "date": "2024-10-25",
        "title": "📈 Ставка ЦБ 21% (Рекорд)",
        "description": "Повышение ключевой ставки ЦБ РФ до исторического рекорда 21.0% годовых для борьбы с инфляцией.",
        "color": "#F4511E"
    }
]


# ==========================================
# 1. ЗАГРУЗКА ИСТОРИЧЕСКИХ ДАННЫХ С ПАГИНАЦИЕЙ
# ==========================================

def _fetch_single_board_candles(ticker: str, board: str, start_date: datetime.date, end_date: datetime.date) -> pd.Series:
    """Загружает свечи конкретного инструмента с указанного борда MOEX ISS с пагинацией."""
    engine = "stock"
    market = "shares" if board in ["TQBR", "TQTF"] else "bonds"
    all_rows = []
    cols = []
    start_offset = 0
    headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"}

    while True:
        url = f"https://iss.moex.com/iss/engines/{engine}/markets/{market}/boards/{board}/securities/{ticker}/candles.json"
        params = {
            "from": start_date.isoformat(),
            "till": end_date.isoformat(),
            "interval": 24,
            "iss.meta": "off",
            "start": start_offset
        }
        try:
            resp = requests.get(url, params=params, headers=headers, timeout=12)
            if resp.status_code == 200:
                data = resp.json().get("candles", {})
                rows = data.get("data", [])
                cols = data.get("columns", [])
                if not rows:
                    break
                all_rows.extend(rows)
                if len(rows) < 500:
                    break
                start_offset += len(rows)
            else:
                break
        except Exception:
            break

    if all_rows and cols:
        df = pd.DataFrame(all_rows, columns=cols)
        if "close" in df.columns and "begin" in df.columns:
            df["begin"] = pd.to_datetime(df["begin"])
            df = df.drop_duplicates(subset=["begin"]).sort_values(by="begin")
            df.set_index("begin", inplace=True)
            return df["close"].astype(float).sort_index()

    return pd.Series(dtype=float)


@st.cache_data(ttl=3600, show_spinner=False)
def fetch_ticker_candles(ticker: str, start_date: datetime.date, end_date: datetime.date) -> pd.Series:
    """Загружает дневные свечи акции или облигации с Мосбиржи через MOEX ISS API с пагинацией и сшивкой редомициляций."""
    # 1. Попытка через moexalgo (только если покрывает требуемый диапазон от начала до конца)
    if Ticker is not None:
        try:
            asset = Ticker(ticker)
            candles_method = getattr(asset, "candles", None)
            if callable(candles_method):
                raw = candles_method(start=start_date.isoformat(), end=end_date.isoformat(), period="1D")
                if isinstance(raw, pd.DataFrame) and not raw.empty and "close" in raw.columns:
                    df = raw.copy()
                    if "begin" in df.columns:
                        df["begin"] = pd.to_datetime(df["begin"])
                        df = df.drop_duplicates(subset=["begin"]).sort_values(by="begin")
                        df.set_index("begin", inplace=True)
                    s = df["close"].astype(float).sort_index()
                    is_start_cov = (s.index[0].date() <= start_date + timedelta(days=45)) or ((end_date - start_date).days <= 60)
                    is_end_cov = s.index[-1].date() >= end_date - timedelta(days=15)
                    if len(s) > 10 and is_start_cov and is_end_cov:
                        return s
        except Exception:
            pass

    # 2. Поиск по бордам акций и облигаций (TQBR, TQTF, TQCB, TQOB)
    boards_to_try = ["TQBR", "TQTF", "TQCB", "TQOB"]
    s = pd.Series(dtype=float)
    for b in boards_to_try:
        s = _fetch_single_board_candles(ticker, b, start_date, end_date)
        if not s.empty:
            break

    # 3. Автоматическая сшивка исторических тикеров редомициляций (YDEX -> YNDX, T -> TCSG, HEAD -> HHRU)
    pred_ticker = PREDECESSOR_MAP.get(ticker)
    if pred_ticker:
        # Если история начинается значительно позже даты старта, подгружаем котировки предшественника
        needs_predecessor = s.empty or (s.index[0].date() > start_date + timedelta(days=60))
        if needs_predecessor:
            s_pred = _fetch_single_board_candles(pred_ticker, "TQBR", start_date, end_date)
            if not s_pred.empty:
                if not s.empty:
                    cutoff = s.index[0] - pd.Timedelta(days=1)
                    s = pd.concat([s_pred.loc[:cutoff], s]).sort_index()
                else:
                    s = s_pred

    return s


@st.cache_data(ttl=3600, show_spinner=False)
def fetch_benchmark_candles(symbol: str, start_date: datetime.date, end_date: datetime.date) -> pd.Series:
    """Загружает дневные свечи бенчмарка (MCFTRR, IMOEX, MCFTR) с Мосбиржи через moexalgo или MOEX ISS API с пагинацией."""
    # 1. Попытка через moexalgo
    if Ticker is not None:
        try:
            asset = Ticker(symbol)
            candles_method = getattr(asset, "candles", None)
            if callable(candles_method):
                raw = candles_method(start=start_date.isoformat(), end=end_date.isoformat(), period="1D")
                if isinstance(raw, pd.DataFrame) and not raw.empty and "close" in raw.columns:
                    df = raw.copy()
                    if "begin" in df.columns:
                        df["begin"] = pd.to_datetime(df["begin"])
                        df = df.drop_duplicates(subset=["begin"]).sort_values(by="begin")
                        df.set_index("begin", inplace=True)
                    s = df["close"].astype(float).sort_index()
                    is_start_cov = (s.index[0].date() <= start_date + timedelta(days=45)) or ((end_date - start_date).days <= 60)
                    is_end_cov = s.index[-1].date() >= end_date - timedelta(days=15)
                    if len(s) > 10 and is_start_cov and is_end_cov:
                        return s
        except Exception:
            pass

    # 2. Резервный шлюз MOEX ISS API (рынок индексов SNDX) с пагинацией
    all_rows = []
    cols = []
    start_offset = 0
    headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"}
    while True:
        url = f"https://iss.moex.com/iss/engines/stock/markets/index/boards/SNDX/securities/{symbol}/candles.json"
        params = {
            "from": start_date.isoformat(),
            "till": end_date.isoformat(),
            "interval": 24,
            "iss.meta": "off",
            "start": start_offset
        }
        try:
            resp = requests.get(url, params=params, headers=headers, timeout=12)
            if resp.status_code == 200:
                data = resp.json().get("candles", {})
                rows = data.get("data", [])
                cols = data.get("columns", [])
                if not rows:
                    break
                all_rows.extend(rows)
                if len(rows) < 500:
                    break
                start_offset += len(rows)
            else:
                break
        except Exception:
            break

    if all_rows and cols:
        df = pd.DataFrame(all_rows, columns=cols)
        if "close" in df.columns and "begin" in df.columns:
            df["begin"] = pd.to_datetime(df["begin"])
            df = df.drop_duplicates(subset=["begin"]).sort_values(by="begin")
            df.set_index("begin", inplace=True)
            return df["close"].astype(float).sort_index()

    return pd.Series(dtype=float)


# ==========================================
# 2. МАТЕМАТИЧЕСКИЙ ДВИЖОК БЭКТЕСТА
# ==========================================

def simulate_portfolio(
    prices_df: pd.DataFrame,
    weights_dict: Dict[str, float],
    initial_capital: float,
    rebalance_freq: str = "M",
    fee_rate: float = 0.0005,
    monthly_contribution: float = 0.0
) -> Tuple[pd.Series, pd.Series, float, pd.Series]:
    """Симулирует динамику стоимости портфеля с учетом весов, комиссий, ребалансировки и регулярных довнесений (DCA)."""
    dates = prices_df.index
    n_days = len(dates)
    tickers = list(weights_dict.keys())

    port_values = pd.Series(index=dates, dtype=float)
    daily_fees = pd.Series(0.0, index=dates, dtype=float)
    invested_series = pd.Series(index=dates, dtype=float)

    # Нормализуем веса к 1.0
    total_w = sum(weights_dict.values())
    norm_weights = {t: weights_dict[t] / total_w for t in tickers}

    # Первичное открытие позиций с учетом комиссии
    init_cost = initial_capital * fee_rate
    capital_after_entry = initial_capital - init_cost
    daily_fees.iloc[0] = init_cost

    units = {t: (capital_after_entry * norm_weights[t]) / prices_df[t].iloc[0] for t in tickers}
    port_values.iloc[0] = capital_after_entry
    cum_invested = initial_capital
    invested_series.iloc[0] = cum_invested

    last_rebal_period = None
    last_dca_period = (dates[0].year, dates[0].month)

    for i in range(1, n_days):
        d = dates[i]
        curr_val = sum(units[t] * prices_df[t].iloc[i] for t in tickers)

        # Регулярное довнесение (DCA) раз в месяц
        curr_month = (d.year, d.month)
        if monthly_contribution > 0 and curr_month != last_dca_period:
            cum_invested += monthly_contribution
            dca_cost = monthly_contribution * fee_rate
            net_dca = monthly_contribution - dca_cost
            daily_fees.iloc[i] += dca_cost
            for t in tickers:
                units[t] += (net_dca * norm_weights[t]) / prices_df[t].iloc[i]
            curr_val = sum(units[t] * prices_df[t].iloc[i] for t in tickers)
            last_dca_period = curr_month

        do_rebal = False
        if rebalance_freq == "M":
            period_key = (d.year, d.month)
            if last_rebal_period is not None and period_key != last_rebal_period:
                do_rebal = True
            last_rebal_period = period_key
        elif rebalance_freq == "Q":
            period_key = (d.year, (d.month - 1) // 3)
            if last_rebal_period is not None and period_key != last_rebal_period:
                do_rebal = True
            last_rebal_period = period_key
        elif rebalance_freq == "Y":
            period_key = d.year
            if last_rebal_period is not None and period_key != last_rebal_period:
                do_rebal = True
            last_rebal_period = period_key

        if do_rebal:
            turnover = 0.0
            for t in tickers:
                curr_asset_val = units[t] * prices_df[t].iloc[i]
                target_asset_val = curr_val * norm_weights[t]
                turnover += abs(target_asset_val - curr_asset_val)
            cost = turnover * fee_rate
            daily_fees.iloc[i] += cost
            net_val = curr_val - cost
            units = {t: (net_val * norm_weights[t]) / prices_df[t].iloc[i] for t in tickers}
            curr_val = net_val

        port_values.iloc[i] = curr_val
        invested_series.iloc[i] = cum_invested

    total_fees_paid = daily_fees.sum()
    return port_values, daily_fees, total_fees_paid, invested_series


def simulate_benchmark(
    bench_series: pd.Series,
    initial_capital: float,
    monthly_contribution: float = 0.0
) -> pd.Series:
    """Симулирует динамику бенчмарка со стартовым капиталом и опциональным довнесением (DCA)."""
    dates = bench_series.index
    n_days = len(dates)
    bench_values = pd.Series(index=dates, dtype=float)

    units = initial_capital / bench_series.iloc[0]
    bench_values.iloc[0] = initial_capital
    last_dca_period = (dates[0].year, dates[0].month)

    for i in range(1, n_days):
        d = dates[i]
        curr_m = (d.year, d.month)
        if monthly_contribution > 0 and curr_m != last_dca_period:
            units += monthly_contribution / bench_series.iloc[i]
            last_dca_period = curr_m
        bench_values.iloc[i] = units * bench_series.iloc[i]

    return bench_values


def simulate_risk_free(
    dates: pd.DatetimeIndex,
    initial_capital: float,
    rf_annual_pct: float,
    monthly_contribution: float = 0.0
) -> pd.Series:
    """Симулирует депозит по ставке ЦБ РФ со сложным процентом и опциональным довнесением (DCA)."""
    n_days = len(dates)
    rf_values = pd.Series(index=dates, dtype=float)
    daily_rate = (1.0 + rf_annual_pct / 100.0) ** (1.0 / 365.25)

    curr_val = initial_capital
    rf_values.iloc[0] = curr_val
    last_dca_period = (dates[0].year, dates[0].month)

    for i in range(1, n_days):
        d = dates[i]
        curr_m = (d.year, d.month)
        days_step = max(1, (d - dates[i-1]).days)
        curr_val = curr_val * (daily_rate ** days_step)
        if monthly_contribution > 0 and curr_m != last_dca_period:
            curr_val += monthly_contribution
            last_dca_period = curr_m
        rf_values.iloc[i] = curr_val

    return rf_values


def calculate_performance_kpis(
    port_values: pd.Series,
    benchmark_values: pd.Series,
    initial_capital: float,
    risk_free_rate_pct: float = 16.0,
    invested_series: Optional[pd.Series] = None
) -> Dict[str, float]:
    """Рассчитывает институциональные коэффициенты эффективности и риска с учетом довнесений."""
    common_idx = port_values.index.intersection(benchmark_values.index)
    pv = port_values.loc[common_idx]
    bv = benchmark_values.loc[common_idx]

    total_invested = float(invested_series.loc[common_idx[-1]]) if (invested_series is not None and not invested_series.empty) else initial_capital

    n_days = (common_idx[-1] - common_idx[0]).days if len(common_idx) > 1 else 1
    years = max(n_days / 365.25, 0.05)

    # 1. Total Return & CAGR
    fin_val = pv.iloc[-1]
    total_ret = ((fin_val / total_invested) - 1.0) * 100.0 if total_invested > 0 else 0.0
    bench_ret = ((bv.iloc[-1] / total_invested) - 1.0) * 100.0 if total_invested > 0 else 0.0

    if fin_val > 0 and total_invested > 0:
        cagr = (((fin_val / total_invested) ** (1.0 / years)) - 1.0) * 100.0
    else:
        cagr = -100.0

    if bv.iloc[-1] > 0 and total_invested > 0:
        bench_cagr = (((bv.iloc[-1] / total_invested) ** (1.0 / years)) - 1.0) * 100.0
    else:
        bench_cagr = -100.0

    # 2. Daily returns
    daily_port_ret = pv.pct_change().dropna()
    daily_bench_ret = bv.pct_change().dropna()

    # 3. Volatility (Annualized)
    ann_vol = daily_port_ret.std() * np.sqrt(252) * 100.0 if len(daily_port_ret) > 1 else 0.0
    bench_ann_vol = daily_bench_ret.std() * np.sqrt(252) * 100.0 if len(daily_bench_ret) > 1 else 0.0

    # 4. Max Drawdown
    peak = pv.cummax()
    dd_series = (pv - peak) / peak
    max_dd = dd_series.min() * 100.0

    bench_peak = bv.cummax()
    bench_dd_series = (bv - bench_peak) / bench_peak
    bench_max_dd = bench_dd_series.min() * 100.0

    # 5. Sharpe Ratio
    rf_dec = risk_free_rate_pct
    sharpe = ((cagr - rf_dec) / ann_vol) if ann_vol > 0 else 0.0

    # 6. Sortino Ratio (только нисходящие отклонения)
    downside_ret = daily_port_ret[daily_port_ret < 0]
    downside_std = downside_ret.std() * np.sqrt(252) * 100.0 if len(downside_ret) > 1 else 0.0
    sortino = ((cagr - rf_dec) / downside_std) if downside_std > 0 else 0.0

    # 7. Calmar Ratio
    calmar = (cagr / abs(max_dd)) if abs(max_dd) > 0.01 else 0.0

    # 8. Beta & Alpha к бенчмарку
    if len(daily_port_ret) > 5 and len(daily_bench_ret) > 5:
        cov = np.cov(daily_port_ret, daily_bench_ret)[0][1]
        bench_var = np.var(daily_bench_ret)
        beta = (cov / bench_var) if bench_var > 0 else 1.0
        alpha = cagr - (rf_dec + beta * (bench_cagr - rf_dec))
    else:
        beta = 1.0
        alpha = 0.0

    # 9. Win rate (доля прибыльных торговых дней)
    win_days = (daily_port_ret > 0).sum()
    total_days = len(daily_port_ret)
    win_rate = (win_days / total_days * 100.0) if total_days > 0 else 50.0

    return {
        "final_capital": pv.iloc[-1],
        "total_invested": total_invested,
        "total_return_pct": total_ret,
        "bench_return_pct": bench_ret,
        "alpha_excess_pct": total_ret - bench_ret,
        "cagr_pct": cagr,
        "bench_cagr_pct": bench_cagr,
        "max_drawdown_pct": max_dd,
        "bench_max_dd_pct": bench_max_dd,
        "volatility_pct": ann_vol,
        "bench_volatility_pct": bench_ann_vol,
        "sharpe_ratio": sharpe,
        "sortino_ratio": sortino,
        "calmar_ratio": calmar,
        "beta": beta,
        "jensen_alpha_pct": alpha,
        "win_rate_pct": win_rate,
        "years": years,
        "trading_days": total_days
    }


# ==========================================
# 3. ИНТЕРФЕЙС И УПРАВЛЕНИЕ СТРАНИЦЕЙ
# ==========================================

st.title("⏳ Исторический Бэктест & Стресс-Тест Портфеля (MOEX)")
st.caption("Симуляция инвестиционных стратегий на реальных исторических котировках Московской биржи с учетом комиссий, ребалансировки и бенчмарка IMOEX.")

st.page_link("streamlit_project.py", label="← Вернуться на Экран инвестора", icon="📊")

with st.expander("📖 Методология и как читать метрики бэктеста", expanded=False):
    st.markdown("""
    **Бэктест (Backtesting)** — это математическая реконструкция того, как вел бы себя портфель в прошлом при соблюдении заданной инвестиционной дисциплины.

    ### Ключевые показатели:
    - **Total Return (%):** полная накопленная доходность стратегии за выбранный исторический отрезок.
    - **CAGR (% годовых):** среднегодовой сложный темп роста капитала (Compound Annual Growth Rate).
    - **Max Drawdown (%):** максимальная просадка от исторического пика капитала (индикатор психологического стресса инвестора).
    - **Sharpe Ratio (Коэффициент Шарпа):** показывает, сколько процентов доходности инвестор получает на единицу общего риска сверх ставки ЦБ. Значение `> 0.5` считается хорошим, `> 1.0` — отличным.
    - **Sortino Ratio (Коэффициент Сортино):** учитывает только отрицательную волатильность (падения), не штрафуя портфель за сильные взлеты цены.
    - **Alpha (Альфа):** чистая избыточная доходность портфеля, созданная за счет качественного отбора акций относительно Индекса МосБиржи.
    - **Beta (Бета):** чувствительность портфеля к рынку. При `Beta = 1.0` портфель движется синхронно с IMOEX; при `Beta < 1.0` портфель более защитный.
    """)

# ------------------------------------------
# Сайдбар: Настройки бэктеста
# ------------------------------------------
st.sidebar.header("⚙️ Параметры бэктеста")

strategy_mode = st.sidebar.selectbox(
    "Выберите стратегию тестирования:",
    options=[
        "💼 Мой текущий портфель",
        "🏆 Топ акций по качеству (Лидеры рынка)",
        "🛠️ Кастомный портфель (Свой выбор)"
    ],
    index=0
)

date_mode = st.sidebar.radio(
    "Выбор временного периода:",
    options=[
        "🎯 Исторические точки (События MOEX)",
        "📆 Произвольный диапазон (Календарь)",
        "⏳ Фиксированный горизонт (от сегодня)"
    ],
    index=0
)

start_date: datetime.date
end_date: datetime.date = datetime.now().date()

if date_mode == "🎯 Исторические точки (События MOEX)":
    event_preset = st.sidebar.selectbox(
        "Точка отсчета бэктеста:",
        options=[
            "💼 21.12.2021 — Первая сделка портфеля (как на izi.invest)",
            "⚔️ 24.02.2022 — Начало СВО (Кризис и заморозка)",
            "🟢 24.03.2022 — Рестарт биржевых торгов MOEX",
            "📢 21.09.2022 — Локальное дно (Мобилизация)",
            "🚀 01.01.2023 — Старт бычьего ралли 2023 года",
            "🏦 15.08.2023 — Внеплановое повышение ставки ЦБ 12%",
            "📅 01.01.2024 — С начала 2024 года (YTD)",
            "🚫 12.06.2024 — Санкции OFAC против Мосбиржи и НКЦ",
            "🏔️ 26.10.2021 — Исторический максимум IMOEX (ATH 4292 п.)",
            "🦠 20.02.2020 — Начало пандемии COVID-19"
        ],
        index=0
    )
    preset_date_map = {
        "💼 21.12.2021": datetime(2021, 12, 21).date(),
        "⚔️ 24.02.2022": datetime(2022, 2, 24).date(),
        "🟢 24.03.2022": datetime(2022, 3, 24).date(),
        "📢 21.09.2022": datetime(2022, 9, 21).date(),
        "🚀 01.01.2023": datetime(2023, 1, 1).date(),
        "🏦 15.08.2023": datetime(2023, 8, 15).date(),
        "📅 01.01.2024": datetime(2024, 1, 1).date(),
        "🚫 12.06.2024": datetime(2024, 6, 12).date(),
        "🏔️ 26.10.2021": datetime(2021, 10, 26).date(),
        "🦠 20.02.2020": datetime(2020, 2, 20).date(),
    }
    matched_dt = None
    for k, v in preset_date_map.items():
        if event_preset.startswith(k):
            matched_dt = v
            break
    start_date = matched_dt or datetime(2021, 12, 21).date()

elif date_mode == "📆 Произвольный диапазон (Календарь)":
    c_d1, c_d2 = st.sidebar.columns(2)
    with c_d1:
        start_date = st.date_input(
            "Дата начала:",
            value=datetime(2021, 12, 21).date(),
            min_value=datetime(2015, 1, 1).date(),
            max_value=datetime.now().date()
        )
    with c_d2:
        end_date = st.date_input(
            "Дата конца:",
            value=datetime.now().date(),
            min_value=start_date,
            max_value=datetime.now().date()
        )
    if start_date >= end_date:
        st.sidebar.error("Дата начала должна быть строго раньше даты окончания.")
        st.stop()

else:  # Фиксированный горизонт (от сегодня)
    horizon_choice = st.sidebar.selectbox(
        "Горизонт тестирования:",
        options=["6 месяцев", "1 год", "2 года", "3 года", "5 лет"],
        index=1
    )
    horizon_days_map = {
        "6 месяцев": 180,
        "1 год": 365,
        "2 года": 730,
        "3 года": 1095,
        "5 лет": 1825
    }
    start_date = end_date - timedelta(days=horizon_days_map[horizon_choice])

show_events_on_chart = st.sidebar.checkbox(
    "🏷️ Маркировать события MOEX на графике",
    value=True,
    help="Отображает вертикальные пунктирные линии ключевых исторических событий (СВО, COVID, мобилизация, ключевая ставка, санкции)"
)

dca_mode = st.sidebar.selectbox(
    "Режим инвестирования капитала:",
    options=[
        "Единоразовый вход (Lump-sum)",
        "Ежемесячное довнесение (DCA)"
    ],
    index=0,
    help="DCA (Dollar-Cost Averaging) — регулярное довнесение средств каждый месяц. Сглаживает просадки при падении рынка и объясняет более высокую доходность на izi.invest за счет покупок на дне 2022 года."
)

monthly_contrib = 0.0
if "DCA" in dca_mode:
    monthly_contrib = st.sidebar.number_input(
        "Ежемесячное пополнение (₽):",
        min_value=5000,
        max_value=10000000,
        value=50000,
        step=5000
    )

handle_young_assets = st.sidebar.selectbox(
    "Активы моложе даты старта (IPO/новые облигации):",
    options=[
        "🛡️ Исключать поздние бумаги (сохранять выбранную дату старта)",
        "⏳ Срезать весь бэктест до даты выхода самой новой бумаги"
    ],
    index=0,
    help="Если в портфеле есть актив, начавший торговаться позже даты старта бэктеста (например, облигация RU000A10D301 от 13.10.2025 или IPO Совкомбанка SVCB от 15.12.2023), по умолчанию он исключается из расчета, чтобы бэктест не схлопывался до 1 года."
)

rebalance_mode_label = st.sidebar.selectbox(
    "Режим ребалансировки долей:",
    options=[
        "Ежемесячно (Monthly)",
        "Ежеквартально (Quarterly)",
        "Ежегодно (Yearly)",
        "Buy & Hold (Без ребалансировки)"
    ],
    index=0
)

rebalance_code_map = {
    "Ежемесячно (Monthly)": "M",
    "Ежеквартально (Quarterly)": "Q",
    "Ежегодно (Yearly)": "Y",
    "Buy & Hold (Без ребалансировки)": "none"
}
rebalance_freq = rebalance_code_map[rebalance_mode_label]

initial_capital = st.sidebar.number_input(
    "Начальный капитал (₽):",
    min_value=50000,
    max_value=100000000,
    value=1000000,
    step=100000
)

broker_fee_pct = st.sidebar.slider(
    "Комиссия брокера за сделку (%):",
    min_value=0.0,
    max_value=0.3,
    value=0.05,
    step=0.01,
    help="Учитывается при первоначальном входе и при каждой ребалансировке портфеля."
)
fee_rate = broker_fee_pct / 100.0

rf_rate_input = st.sidebar.slider(
    "Безрисковая ставка (Ставка ЦБ, % годовых):",
    min_value=5.0,
    max_value=25.0,
    value=16.0,
    step=0.5,
    help="Используется как базовая планка альтернативной доходности для расчета Sharpe и Sortino."
)

benchmark_choice = st.sidebar.selectbox(
    "Основной бенчмарк для сравнения:",
    options=[
        "MCFTRR (Индекс полной доходности «нетто») [Как в izi.invest]",
        "IMOEX (Ценовой Индекс МосБиржи без див.)",
        "MCFTR (Индекс полной доходности «брутто»)"
    ],
    index=0,
    help="MCFTRR — эталонный индекс Мосбиржи полной доходности (Total Return Net). Учитывает реинвестирование дивидендов после уплаты 13% НДФЛ. IMOEX — ценовой индекс (Price Return) без учета дивидендов, занижающий реальную доходность рынка на 10-14% ежегодно из-за дивгэпов."
)

if "MCFTRR" in benchmark_choice:
    primary_bench_symbol = "MCFTRR"
    primary_bench_label = "MCFTRR (Полная доходность «нетто»)"
elif "брутто" in benchmark_choice:
    primary_bench_symbol = "MCFTR"
    primary_bench_label = "MCFTR (Полная доходность «брутто»)"
else:
    primary_bench_symbol = "IMOEX"
    primary_bench_label = "Индекс МосБиржи (IMOEX)"

# Формирование тикеров и весов
selected_weights: Dict[str, float] = {}

if strategy_mode.startswith("💼 Мой текущий"):
    # Проверяем, есть ли переданные веса из раздела "Реальный Портфель и Сделки"
    custom_w = st.session_state.get("backtest_custom_weights", {})
    loaded_port = st.session_state.get("my_portfolio", {})
    if custom_w:
        selected_weights = custom_w.copy()
        st.sidebar.success(f"Загружено {len(custom_w)} активов из реального портфеля!")
    elif loaded_port:
        user_tickers = list(loaded_port.keys())
        st.sidebar.success(f"Загружено {len(user_tickers)} акций из вашего файла")
        # Веса пропорционально текущей стоимости
        tot_v = sum(v.get("current_value", 1.0) for v in loaded_port.values())
        for t, v in loaded_port.items():
            selected_weights[t] = v.get("current_value", 1.0) / tot_v if tot_v > 0 else 1.0 / len(user_tickers)
    else:
        st.sidebar.info("Файл портфеля не загружен — используется базовый портфель стратегии")
        for t in DEFAULT_PORTFOLIO_TICKERS:
            selected_weights[t] = 1.0 / len(DEFAULT_PORTFOLIO_TICKERS)

elif strategy_mode.startswith("🏆 Топ акций"):
    top_tickers = ["SBER", "LKOH", "ROSN", "NVTK", "T", "CHMF", "TRNFP", "TATN", "HEAD", "MGNT"]
    st.sidebar.caption(f"Топ-{len(top_tickers)} акций с высшим качеством и див. надежностью")
    for t in top_tickers:
        selected_weights[t] = 1.0 / len(top_tickers)

else:  # Кастомный портфель
    custom_chosen = st.sidebar.multiselect(
        "Выберите акции для портфеля:",
        options=POPULAR_LIQUID_TICKERS,
        default=["SBER", "LKOH", "ROSN", "NVTK", "YDEX", "CHMF"]
    )
    if custom_chosen:
        for t in custom_chosen:
            selected_weights[t] = 1.0 / len(custom_chosen)

# ------------------------------------------
# Запуск расчетов
# ------------------------------------------

if not selected_weights:
    st.warning("Выберите хотя бы один актив для запуска бэктеста.")
    st.stop()

period_label = f"{start_date.strftime('%d.%m.%Y')} — {end_date.strftime('%d.%m.%Y')}"

with st.spinner(f"Загружаю котировки за период {period_label} с Мосбиржи и симулирую портфель..."):
    # 1. Загрузка цен активов
    prices_collector: Dict[str, pd.Series] = {}
    missing_tickers: List[str] = []

    for t in selected_weights.keys():
        s = fetch_ticker_candles(t, start_date, end_date)
        if not s.empty and len(s) > 10:
            prices_collector[t] = s
        else:
            missing_tickers.append(t)

    # 2. Загрузка основного и вспомогательного бенчмарка (MCFTRR + IMOEX)
    primary_bench_series = fetch_benchmark_candles(primary_bench_symbol, start_date, end_date)
    companion_symbol = "IMOEX" if primary_bench_symbol != "IMOEX" else "MCFTRR"
    companion_bench_series = fetch_benchmark_candles(companion_symbol, start_date, end_date)

if missing_tickers:
    st.sidebar.warning(f"Недостаточно котировок для тикеров: {', '.join(missing_tickers)}. Они исключены из бэктеста.")
    for mt in missing_tickers:
        selected_weights.pop(mt, None)

# Анализ даты первой свечи для каждого актива
late_assets = {}
cutoff_threshold = start_date + timedelta(days=90)

for t, s in prices_collector.items():
    if not s.empty and s.index[0].date() > cutoff_threshold:
        late_assets[t] = s.index[0].date()

# Обработка молодых бумаг (IPO/новые облигации)
if late_assets:
    if handle_young_assets.startswith("🛡️") and len(prices_collector) > len(late_assets):
        # Исключаем поздние бумаги, чтобы сохранить полный выбранный горизонт дат
        excluded_tickers = list(late_assets.keys())
        for et in excluded_tickers:
            prices_collector.pop(et, None)
            selected_weights.pop(et, None)

        # Нормализуем оставшиеся веса
        if selected_weights:
            tot_w = sum(selected_weights.values())
            for t in selected_weights:
                selected_weights[t] = selected_weights[t] / tot_w

        late_desc = ", ".join(f"**{t}** (с {d.strftime('%d.%m.%Y')})" for t, d in late_assets.items())
        st.sidebar.info(
            f"ℹ️ Для сохранения горизонта с **{start_date.strftime('%d.%m.%Y')}** исключены активы, начавшие торговаться позже: {late_desc}. "
            f"Их веса перераспределены между остальными {len(selected_weights)} бумагами."
        )
    else:
        # Режим сжатия горизонта до даты самой новой бумаги
        latest_start = max(late_assets.values())
        st.sidebar.warning(
            f"⚠️ Горизонт бэктеста сокращен до даты старта самого молодого актива: **{latest_start.strftime('%d.%m.%Y')}**."
        )

if len(prices_collector) < 1 or primary_bench_series.empty:
    st.error("Не удалось сформировать исторические ряды котировок для выбранного периода. Попробуйте другой горизонт.")
    st.stop()

# Формируем матрицу цен и выравниваем даты
raw_price_df = pd.DataFrame(prices_collector).dropna()
aligned_dates = raw_price_df.index.intersection(primary_bench_series.index)

if len(aligned_dates) < 20:
    st.error(f"Слишком мало совпадающих торговых дней ({len(aligned_dates)}). Выберите более длительный горизонт.")
    st.stop()

prices_df = raw_price_df.loc[aligned_dates].copy()
bench_df = primary_bench_series.loc[aligned_dates].copy()

# Масштабируем основной бенчмарк к стартовому капиталу (с поддержкой DCA)
bench_scaled = simulate_benchmark(
    primary_bench_series.loc[aligned_dates],
    initial_capital,
    monthly_contribution=monthly_contrib
)

# Масштабируем вспомогательный бенчмарк (если доступен)
has_companion = not companion_bench_series.empty
if has_companion:
    companion_aligned = companion_bench_series.reindex(aligned_dates).ffill().bfill()
    companion_scaled = simulate_benchmark(
        companion_aligned,
        initial_capital,
        monthly_contribution=monthly_contrib
    )
else:
    companion_scaled = pd.Series(dtype=float)

# Запуск симуляции портфеля (с поддержкой DCA)
port_series, fee_series, total_fees, invested_series = simulate_portfolio(
    prices_df,
    selected_weights,
    initial_capital,
    rebalance_freq=rebalance_freq,
    fee_rate=fee_rate,
    monthly_contribution=monthly_contrib
)

# Линия безрисковой доходности (вклад по ставке ЦБ с поддержкой DCA)
rf_series = simulate_risk_free(
    aligned_dates,
    initial_capital,
    rf_rate_input,
    monthly_contribution=monthly_contrib
)

# Расчет всех метрик с учетом динамики довнесений
kpis = calculate_performance_kpis(
    port_series,
    bench_scaled,
    initial_capital,
    risk_free_rate_pct=rf_rate_input,
    invested_series=invested_series
)

# ==========================================
# 4. ВЫВОД РЕЗУЛЬТАТОВ (KPI METRICS)
# ==========================================

# Информационная плашка о специфике бенчмарка в РФ (как на izi.invest)
with st.expander("💡 Разница между Индексами IMOEX и MCFTRR (Специфика РФ)", expanded=False):
    st.markdown("""
    - **Индекс МосБиржи (IMOEX)** — *ценовой индекс* (Price Return). Он фиксирует только изменение котировок и «теряет» все дивидендные гэпы. На дивидендном рынке РФ это занижает доходность на 9–14% в год!
    - **Индекс полной доходности «нетто» (MCFTRR)** — *эталонный бенчмарк* (Total Return Net). Он учитывает автоматическое реинвестирование дивидендов за вычетом 13% НДФЛ. Именно с ним профессиональные фонды и сервис **izi.invest** сравнивают доходность портфелей.
    - **За 3–4 года** разрыв между ценовым IMOEX и полной доходностью MCFTRR на Мосбирже достигает **25–35%**!
    """)

st.info(
    f"📅 **Фактический период бэктеста:** с **{aligned_dates[0].strftime('%d.%m.%Y')}** по **{aligned_dates[-1].strftime('%d.%m.%Y')}** "
    f"({len(aligned_dates)} торговых дней, ~{kpis['years']:.1f} года). Активов в расчете: **{len(prices_df.columns)}** "
    f"({', '.join(sorted(prices_df.columns))})."
)

m_c1, m_c2, m_c3, m_c4 = st.columns(4)

final_cap = kpis["final_capital"]
tot_invested = kpis["total_invested"]
profit_rub = final_cap - tot_invested
tot_ret = kpis["total_return_pct"]
bench_ret = kpis["bench_return_pct"]
excess_ret = kpis["alpha_excess_pct"]

delta_label = f"{profit_rub:+,.0f} ₽ ({tot_ret:+.1f}%)"
if monthly_contrib > 0:
    delta_label += f" | Вложено: {tot_invested:,.0f} ₽"

m_c1.metric(
    label="Итоговый капитал",
    value=f"{final_cap:,.0f} ₽",
    delta=delta_label
)

m_c2.metric(
    label=f"Доходность vs {primary_bench_symbol}",
    value=f"{tot_ret:+.1f}%",
    delta=f"{excess_ret:+.1f}% к бенчмарку" if excess_ret != 0 else "На уровне бенчмарка"
)

m_c3.metric(
    label="CAGR (Годовая доходность)",
    value=f"{kpis['cagr_pct']:+.1f}%",
    delta=f"vs {primary_bench_symbol} {kpis['bench_cagr_pct']:+.1f}%"
)

m_c4.metric(
    label="Макс. просадка (Max DD)",
    value=f"{kpis['max_drawdown_pct']:.1f}%",
    delta=f"vs {primary_bench_symbol} {kpis['bench_max_dd_pct']:.1f}%",
    delta_color="inverse"
)

st.markdown("---")

# ==========================================
# 5. ТАБЫ С ВИЗУАЛИЗАЦИЕЙ И АНАЛИТИКОЙ
# ==========================================

tab_curves, tab_risks, tab_attribution, tab_monthly = st.tabs([
    "📈 Кривая капитала (Equity Curve)",
    "🌊 Риск и Просадки (Drawdowns)",
    "🎯 Вклад активов (Attribution)",
    "📅 Помесячная доходность (Matrix)"
])

# ------------------------------------------
# ТАБ 1: КРИВАЯ КАПИТАЛА
# ------------------------------------------
with tab_curves:
    st.subheader("📈 Динамика стоимости портфеля во времени")
    st.caption(f"Период: {aligned_dates[0].strftime('%d.%m.%Y')} — {aligned_dates[-1].strftime('%d.%m.%Y')} ({kpis['trading_days']} торговых дней). Сравнение с индексами Мосбиржи и безрисковой ставкой.")

    display_mode = st.radio("Отображение шкалы:", ["В процентах доходности (%) [Как izi.invest]", "В рублях (Стоимость капитала)"], horizontal=True)

    companion_label = "Индекс МосБиржи (IMOEX)" if primary_bench_symbol != "IMOEX" else "MCFTRR (Полная доходность «нетто»)"

    if display_mode.startswith("В рублях"):
        chart_dict = {
            "Дата": aligned_dates,
            "Портфель стратегии": port_series.values,
            primary_bench_label: bench_scaled.values,
            f"Ставка ЦБ РФ ({rf_rate_input:.1f}%)": rf_series.values
        }
        if monthly_contrib > 0:
            chart_dict["Вложенный капитал (DCA)"] = invested_series.values
        if has_companion and len(companion_scaled) == len(aligned_dates):
            chart_dict[companion_label] = companion_scaled.values
        val_title = "Капитал, ₽"
    else:
        # В процентах доходности от вложенного капитала (как на izi.invest)
        chart_dict = {
            "Дата": aligned_dates,
            "Портфель стратегии": ((port_series.values / invested_series.values) - 1.0) * 100.0,
            primary_bench_label: ((bench_scaled.values / invested_series.values) - 1.0) * 100.0,
            f"Ставка ЦБ РФ ({rf_rate_input:.1f}%)": ((rf_series.values / invested_series.values) - 1.0) * 100.0
        }
        if has_companion and len(companion_scaled) == len(aligned_dates):
            chart_dict[companion_label] = ((companion_scaled.values / invested_series.values) - 1.0) * 100.0
        val_title = "Доходность, %"

    chart_df = pd.DataFrame(chart_dict)
    melted_chart_df = chart_df.melt(id_vars=["Дата"], var_name="Инструмент", value_name="Значение")

    color_domain = [
        "Портфель стратегии",
        "MCFTRR (Полная доходность «нетто»)",
        "Индекс МосБиржи (IMOEX)",
        "MCFTR (Полная доходность «брутто»)",
        f"Ставка ЦБ РФ ({rf_rate_input:.1f}%)",
        "Вложенный капитал (DCA)"
    ]
    color_range = [
        "#00BCD4",  # Голубой (как Ликвидная часть на izi.invest)
        "#EC407A",  # Розовый (как MCFTRR на izi.invest)
        "#7986CB",  # Фиолетовый (как IMOEX на izi.invest)
        "#AB47BC",  # Пурпурный
        "#FFB300",  # Янтарный (ставка ЦБ)
        "#90A4AE"   # Серый (тело капитала DCA)
    ]

    base_curve_chart = alt.Chart(melted_chart_df).mark_line().encode(
        x=alt.X("Дата:T", title="Дата"),
        y=alt.Y("Значение:Q", title=val_title),
        color=alt.Color("Инструмент:N", scale=alt.Scale(
            domain=color_domain,
            range=color_range
        )),
        strokeWidth=alt.condition(alt.datum.Инструмент == "Портфель стратегии", alt.value(2.8), alt.value(1.8)),
        tooltip=["Дата:T", "Инструмент:N", alt.Tooltip("Значение:Q", format=",.1f")]
    )

    # Поиск исторических событий MOEX в рамках выбранного диапазона дат
    active_events = []
    min_chart_dt = aligned_dates[0]
    max_chart_dt = aligned_dates[-1]

    for ev in MOEX_HISTORICAL_EVENTS:
        ev_dt = pd.to_datetime(ev["date"])
        if min_chart_dt <= ev_dt <= max_chart_dt:
            active_events.append({
                "Дата": ev_dt,
                "Событие": ev["title"],
                "Описание": ev["description"],
                "Цвет": ev["color"]
            })

    if show_events_on_chart and active_events:
        events_df = pd.DataFrame(active_events)
        event_rules = alt.Chart(events_df).mark_rule(
            strokeDash=[4, 4],
            size=1.5,
            opacity=0.75
        ).encode(
            x="Дата:T",
            color=alt.Color("Цвет:N", scale=None),
            tooltip=["Дата:T", "Событие:N", "Описание:N"]
        )

        event_text = alt.Chart(events_df).mark_text(
            align="left",
            baseline="top",
            dx=5,
            dy=6,
            fontSize=11,
            fontWeight="bold"
        ).encode(
            x="Дата:T",
            y=alt.value(6),
            text="Событие:N",
            color=alt.Color("Цвет:N", scale=None)
        )

        final_curve = alt.layer(base_curve_chart, event_rules, event_text).properties(height=440).interactive()
    else:
        final_curve = base_curve_chart.properties(height=440).interactive()

    st.altair_chart(final_curve, width="stretch")

    if active_events:
        with st.expander(f"🏛️ Хронология исторических событий на Мосбирже ({len(active_events)} событий в выбранном периоде)", expanded=False):
            st.markdown("Ключевые геополитические, регуляторные и макроэкономические вехи, повлиявшие на динамику рынка:")
            for ev in active_events:
                ev_formatted = ev["Дата"].strftime("%d.%m.%Y")
                st.markdown(f"- **{ev_formatted} — {ev['Событие']}:** {ev['Описание']}")

    c_fee1, c_fee2 = st.columns(2)
    with c_fee1:
        st.info(f"💡 **Уплаченные комиссии брокеру:** `{total_fees:,.1f} ₽` (ставка `{broker_fee_pct:.2f}%` при входе и ребалансировках).")
    with c_fee2:
        if excess_ret > 0:
            st.success(f"🚀 **Альфа стратегии:** портфель опередил {primary_bench_symbol} на **+{excess_ret:.1f}%**.")
        else:
            st.warning(f"⚠️ **Отставание от бенчмарка:** портфель уступил {primary_bench_symbol} **{excess_ret:.1f}%**.")

# ------------------------------------------
# ТАБ 2: РИСК И ПРОСАДКИ
# ------------------------------------------
with tab_risks:
    st.subheader("🌊 Подводный график просадок (Underwater Chart)")
    st.caption("Показывает глубину падений от локальных пиков капитала и скорость восстановления портфеля.")

    port_peak = port_series.cummax()
    port_dd = ((port_series - port_peak) / port_peak) * 100.0

    bench_p = bench_scaled.cummax()
    bench_dd = ((bench_scaled - bench_p) / bench_p) * 100.0

    dd_df = pd.DataFrame({
        "Дата": aligned_dates,
        "Просадка портфеля (%)": port_dd.values,
        f"Просадка {primary_bench_symbol} (%)": bench_dd.values
    })

    dd_melted = dd_df.melt(id_vars=["Дата"], var_name="Индикатор", value_name="Просадка, %")

    dd_chart = alt.Chart(dd_melted).mark_area(opacity=0.35).encode(
        x=alt.X("Дата:T", title="Дата"),
        y=alt.Y("Просадка, %:Q", title="Просадка от пика, %"),
        color=alt.Color("Индикатор:N", scale=alt.Scale(
            domain=["Просадка портфеля (%)", f"Просадка {primary_bench_symbol} (%)"],
            range=["#FF1744", "#EC407A" if primary_bench_symbol == "MCFTRR" else "#2979FF"]
        )),
        tooltip=["Дата:T", "Индикатор:N", alt.Tooltip("Просадка, %:Q", format=".2f")]
    )

    if show_events_on_chart and active_events:
        dd_rules = alt.Chart(pd.DataFrame(active_events)).mark_rule(
            strokeDash=[4, 4],
            size=1.2,
            opacity=0.65
        ).encode(
            x="Дата:T",
            color=alt.Color("Цвет:N", scale=None),
            tooltip=["Дата:T", "Событие:N", "Описание:N"]
        )
        final_dd_chart = alt.layer(dd_chart, dd_rules).properties(height=320).interactive()
    else:
        final_dd_chart = dd_chart.properties(height=320).interactive()

    st.altair_chart(final_dd_chart, width="stretch")

    st.markdown("#### 📋 Институциональные коэффициенты риска и устойчивости")
    rk1, rk2, rk3, rk4 = st.columns(4)
    rk1.metric("Sharpe Ratio", f"{kpis['sharpe_ratio']:.2f}", "Норма > 0.5" if kpis['sharpe_ratio'] > 0.5 else "Слабая отдача к риску")
    rk2.metric("Sortino Ratio", f"{kpis['sortino_ratio']:.2f}", "С учетом downside риска")
    rk3.metric("Calmar Ratio", f"{kpis['calmar_ratio']:.2f}", "CAGR / |MaxDD|")
    rk4.metric(f"Бета к {primary_bench_symbol}", f"{kpis['beta']:.2f}", "Защитный" if kpis['beta'] < 1.0 else "Агрессивнее рынка")

    rk5, rk6, rk7, rk8 = st.columns(4)
    rk5.metric("Волатильность портфеля", f"{kpis['volatility_pct']:.1f}%", f"{primary_bench_symbol}: {kpis['bench_volatility_pct']:.1f}%")
    rk6.metric("Jensen's Alpha", f"{kpis['jensen_alpha_pct']:+.1f}%", f"Превышение модели CAPM к {primary_bench_symbol}")
    rk7.metric("Win Rate (Прибыльные дни)", f"{kpis['win_rate_pct']:.1f}%", "Доля зеленых сессий")
    rk8.metric("Торговых дней", f"{kpis['trading_days']} дн.", f"{kpis['years']:.1f} года")

# ------------------------------------------
# ТАБ 3: ВКЛАД АКТИВОВ (ATTRIBUTION)
# ------------------------------------------
with tab_attribution:
    st.subheader("🎯 Вклад отдельных активов в результат портфеля")
    st.caption("Определяет драйверов доходности и аутсайдеров, тянувших портфель вниз.")

    attr_rows = []
    tot_w = sum(selected_weights.values())

    for t in selected_weights.keys():
        if t in prices_df.columns:
            s_price = prices_df[t].iloc[0]
            e_price = prices_df[t].iloc[-1]
            ret_pct = ((e_price / s_price) - 1.0) * 100.0
            w_pct = (selected_weights[t] / tot_w) * 100.0
            # Вклад в доходность портфеля = вес * доходность
            contribution_pct = (w_pct / 100.0) * ret_pct
            attr_rows.append({
                "Тикер": t,
                "Вес в портфеле, %": round(w_pct, 1),
                "Стартовая цена, ₽": round(s_price, 2),
                "Текущая цена, ₽": round(e_price, 2),
                "Доходность акции, %": round(ret_pct, 2),
                "Вклад в портфель, %": round(contribution_pct, 2)
            })

    df_attr = pd.DataFrame(attr_rows)
    if not df_attr.empty:
        df_attr = df_attr.sort_values(by="Вклад в портфель, %", ascending=False)

        # Столбчатый график вклада
        attr_chart = alt.Chart(df_attr).mark_bar().encode(
            x=alt.X("Вклад в портфель, %:Q", title="Вклад в доходность портфеля, %"),
            y=alt.Y("Тикер:N", sort="-x", title="Актив"),
            color=alt.condition(
                alt.datum["Вклад в портфель, %"] > 0,
                alt.value("#00E676"),
                alt.value("#FF1744")
            ),
            tooltip=["Тикер:N", "Вклад в портфель, %:Q", "Доходность акции, %:Q", "Вес в портфеле, %:Q"]
        ).properties(height=350)

        st.altair_chart(attr_chart, width="stretch")

        st.markdown("##### 📋 Детальная таблица результативности компонентов портфеля")
        st.dataframe(
            df_attr,
            width="stretch",
            hide_index=True,
            column_config={
                "Доходность акции, %": st.column_config.NumberColumn(
                    "Доходность акции, %",
                    format="%.2f%%"
                ),
                "Вклад в портфель, %": st.column_config.NumberColumn(
                    "Вклад в портфель, %",
                    format="%+.2f%%"
                )
            }
        )

# ------------------------------------------
# ТАБ 4: МАТРИЦА ПОМЕСЯЧНОЙ ДОХОДНОСТИ
# ------------------------------------------
with tab_monthly:
    st.subheader("📅 Матрица помесячной доходности стратегии")
    st.caption("Помесячные результаты в % позволяют выявить сезонность и стабильность генерации прибыли.")

    # Рассчитываем доходность по месяцам
    port_m_df = pd.DataFrame({"capital": port_series})
    port_m_df["year"] = port_m_df.index.year
    port_m_df["month"] = port_m_df.index.month

    # Берем первое и последнее значение каждого месяца
    monthly_groups = port_m_df.groupby(["year", "month"])
    monthly_records = []

    for (yr, mo), grp in monthly_groups:
        m_start = grp["capital"].iloc[0]
        m_end = grp["capital"].iloc[-1]
        m_ret = ((m_end / m_start) - 1.0) * 100.0
        monthly_records.append({
            "Год": yr,
            "Месяц": mo,
            "Доходность, %": round(m_ret, 2)
        })

    if monthly_records:
        df_m = pd.DataFrame(monthly_records)
        month_names = {
            1: "Янв", 2: "Фев", 3: "Мар", 4: "Апр", 5: "Май", 6: "Июн",
            7: "Июл", 8: "Авг", 9: "Сен", 10: "Окт", 11: "Ноя", 12: "Дек"
        }
        df_m["Месяц_Имя"] = df_m["Месяц"].map(month_names)

        pivot_m = df_m.pivot(index="Год", columns="Месяц_Имя", values="Доходность, %")
        # Упорядочиваем месяцы
        ordered_cols = [m for m in month_names.values() if m in pivot_m.columns]
        pivot_m = pivot_m[ordered_cols]

        # Добавляем YTD доходность года
        ytd_map = {}
        for yr, grp in port_m_df.groupby("year"):
            ytd_ret = ((grp["capital"].iloc[-1] / grp["capital"].iloc[0]) - 1.0) * 100.0
            ytd_map[yr] = round(ytd_ret, 2)

        pivot_m["YTD (Год)"] = pd.Series(ytd_map)

        st_styled = pivot_m.style.format("{:+.2f}%", na_rep="—")
        try:
            st_styled = st_styled.background_gradient(
                cmap="RdYlGn",
                subset=ordered_cols,
                vmin=-15.0,
                vmax=15.0
            )
        except Exception:
            # Безопасный fallback без жесткой зависимости от matplotlib
            def _color_ret(val):
                if pd.isna(val) or not isinstance(val, (int, float)):
                    return ""
                intensity = min(abs(val) / 15.0, 1.0)
                alpha = 0.15 + 0.45 * intensity
                if val > 0:
                    return f"background-color: rgba(46, 204, 113, {alpha:.2f}); color: white; font-weight: 500;"
                elif val < 0:
                    return f"background-color: rgba(231, 76, 60, {alpha:.2f}); color: white; font-weight: 500;"
                return "color: #888888;"

            if hasattr(st_styled, "map"):
                st_styled = st_styled.map(_color_ret, subset=ordered_cols)
            elif hasattr(st_styled, "applymap"):
                st_styled = st_styled.applymap(_color_ret, subset=ordered_cols)

        st.dataframe(
            st_styled,
            width="stretch"
        )
    else:
        st.info("Недостаточно данных для построения помесячной матрицы.")
