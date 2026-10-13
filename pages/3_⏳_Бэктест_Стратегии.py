"""Страница исторического бэктеста и стресс-тестирования портфеля на данных MOEX.

Позволяет симулировать поведение портфеля на реальных исторических котировках Московской биржи,
сравнивать результаты с Индексом МосБиржи (IMOEX) и безрисковой ставкой ЦБ РФ,
тестировать различные режимы ребалансировки (Buy & Hold, ежемесячно, ежеквартально)
и рассчитывать ключевые институциональные риск-метрики (Sharpe, Sortino, Calmar, Max Drawdown, Alpha, Beta).
"""

import sys
from datetime import datetime, timedelta
from pathlib import Path
from typing import Dict, List, Tuple

import altair as alt
import numpy as np
import pandas as pd
import requests
import streamlit as st

st.set_page_config(
    page_title="Бэктест Портфеля MOEX",
    page_icon="⏳",
    layout="wide"
)

try:
    from moexalgo import Ticker
except ImportError:
    Ticker = None

DEFAULT_PORTFOLIO_TICKERS = [
    "MGNT", "SBER", "ROSN", "NMTP", "SVCB",
    "T", "SIBN", "BELU", "CHMF", "NLMK",
    "SNGS", "TRNFP", "GAZP"
]

POPULAR_LIQUID_TICKERS = [
    "SBER", "GAZP", "LKOH", "ROSN", "NVTK", "GMKN", "CHMF", "NLMK",
    "MAGN", "PLZL", "ALRS", "VTBR", "T", "SVCB", "BSPB", "MTSS",
    "MGNT", "SMLT", "SGZH", "AFLT", "RTKM", "PHOR", "TATN", "SIBN",
    "TRNFP", "FLOT", "AFKS", "SELG", "HEAD", "YDEX", "OZON", "BELU", "NMTP"
]


# ==========================================
# 1. ЗАГРУЗКА ИСТОРИЧЕСКИХ ДАННЫХ
# ==========================================

@st.cache_data(ttl=3600, show_spinner=False)
def fetch_ticker_candles(ticker: str, start_date: datetime.date, end_date: datetime.date) -> pd.Series:
    """Загружает дневные свечи акции с Мосбиржи через moexalgo или резервный MOEX ISS API."""
    # 1. Попытка через moexalgo
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
                        df.set_index("begin", inplace=True)
                    return df["close"].astype(float).sort_index()
                elif isinstance(raw, (list, tuple)) and raw:
                    df = pd.DataFrame(raw)
                    if "close" in df.columns and "begin" in df.columns:
                        df["begin"] = pd.to_datetime(df["begin"])
                        df.set_index("begin", inplace=True)
                        return df["close"].astype(float).sort_index()
        except Exception:
            pass

    # 2. Резервный шлюз MOEX ISS API
    url = f"https://iss.moex.com/iss/engines/stock/markets/shares/boards/TQBR/securities/{ticker}/candles.json"
    params = {
        "from": start_date.isoformat(),
        "till": end_date.isoformat(),
        "interval": 24,
        "iss.meta": "off"
    }
    try:
        resp = requests.get(url, params=params, timeout=12)
        if resp.status_code == 200:
            data = resp.json().get("candles", {})
            rows = data.get("data", [])
            cols = data.get("columns", [])
            if rows and cols:
                df = pd.DataFrame(rows, columns=cols)
                if "close" in df.columns and "begin" in df.columns:
                    df["begin"] = pd.to_datetime(df["begin"])
                    df.set_index("begin", inplace=True)
                    return df["close"].astype(float).sort_index()
    except Exception:
        pass

    return pd.Series(dtype=float)


@st.cache_data(ttl=3600, show_spinner=False)
def fetch_benchmark_candles(start_date: datetime.date, end_date: datetime.date) -> pd.Series:
    """Загружает дневные свечи Индекса МосБиржи (IMOEX)."""
    url = "https://iss.moex.com/iss/engines/stock/markets/index/boards/SNDX/securities/IMOEX/candles.json"
    params = {
        "from": start_date.isoformat(),
        "till": end_date.isoformat(),
        "interval": 24,
        "iss.meta": "off"
    }
    try:
        resp = requests.get(url, params=params, timeout=12)
        if resp.status_code == 200:
            data = resp.json().get("candles", {})
            rows = data.get("data", [])
            cols = data.get("columns", [])
            if rows and cols:
                df = pd.DataFrame(rows, columns=cols)
                if "close" in df.columns and "begin" in df.columns:
                    df["begin"] = pd.to_datetime(df["begin"])
                    df.set_index("begin", inplace=True)
                    return df["close"].astype(float).sort_index()
    except Exception:
        pass
    return pd.Series(dtype=float)


# ==========================================
# 2. МАТЕМАТИЧЕСКИЙ ДВИЖОК БЭКТЕСТА
# ==========================================

def simulate_portfolio(
    prices_df: pd.DataFrame,
    weights_dict: Dict[str, float],
    initial_capital: float,
    rebalance_freq: str = "M",
    fee_rate: float = 0.0005
) -> Tuple[pd.Series, pd.Series, float]:
    """Симулирует динамику стоимости портфеля с учетом весов, комиссий и периодической ребалансировки."""
    dates = prices_df.index
    n_days = len(dates)
    tickers = list(weights_dict.keys())

    port_values = pd.Series(index=dates, dtype=float)
    daily_fees = pd.Series(0.0, index=dates, dtype=float)

    # Нормализуем веса к 1.0
    total_w = sum(weights_dict.values())
    norm_weights = {t: weights_dict[t] / total_w for t in tickers}

    # Первичное открытие позиций с учетом комиссии
    init_cost = initial_capital * fee_rate
    capital_after_entry = initial_capital - init_cost
    daily_fees.iloc[0] = init_cost

    units = {t: (capital_after_entry * norm_weights[t]) / prices_df[t].iloc[0] for t in tickers}
    port_values.iloc[0] = capital_after_entry

    last_rebal_period = None

    for i in range(1, n_days):
        d = dates[i]
        curr_val = sum(units[t] * prices_df[t].iloc[i] for t in tickers)

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
            daily_fees.iloc[i] = cost
            net_val = curr_val - cost
            units = {t: (net_val * norm_weights[t]) / prices_df[t].iloc[i] for t in tickers}
            curr_val = net_val

        port_values.iloc[i] = curr_val

    total_fees_paid = daily_fees.sum()
    return port_values, daily_fees, total_fees_paid


def calculate_performance_kpis(
    port_values: pd.Series,
    benchmark_values: pd.Series,
    initial_capital: float,
    risk_free_rate_pct: float = 16.0
) -> Dict[str, float]:
    """Рассчитывает институциональные коэффициенты эффективности и риска."""
    common_idx = port_values.index.intersection(benchmark_values.index)
    pv = port_values.loc[common_idx]
    bv = benchmark_values.loc[common_idx]

    n_days = (common_idx[-1] - common_idx[0]).days if len(common_idx) > 1 else 1
    years = max(n_days / 365.25, 0.05)

    # 1. Total Return & CAGR
    total_ret = ((pv.iloc[-1] / initial_capital) - 1.0) * 100.0
    bench_ret = ((bv.iloc[-1] / bv.iloc[0]) - 1.0) * 100.0

    cagr = (((pv.iloc[-1] / initial_capital) ** (1.0 / years)) - 1.0) * 100.0
    bench_cagr = (((bv.iloc[-1] / bv.iloc[0]) ** (1.0 / years)) - 1.0) * 100.0

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

    # 8. Beta & Alpha к IMOEX
    if len(daily_port_ret) > 5 and len(daily_bench_ret) > 5:
        cov = np.cov(daily_port_ret, daily_bench_ret)[0][1]
        bench_var = np.var(daily_bench_ret)
        beta = (cov / bench_var) if bench_var > 0 else 1.0
        # Дженсен Альфа в годовом выражении
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

st.page_link("streamlit_project.py", label="← Вернуться к главному дашборду и рейтингу", icon="🎯")

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
backtest_days = horizon_days_map[horizon_choice]

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

# Формирование тикеров и весов
selected_weights: Dict[str, float] = {}

if strategy_mode.startswith("💼 Мой текущий"):
    # Проверяем, есть ли загруженный портфель в сессии
    loaded_port = st.session_state.get("my_portfolio", {})
    if loaded_port:
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

end_date = datetime.now().date()
start_date = end_date - timedelta(days=backtest_days)

with st.spinner(f"Загружаю котировки за {horizon_choice} с Мосбиржи и симулирую портфель..."):
    # 1. Загрузка цен активов
    prices_collector: Dict[str, pd.Series] = {}
    missing_tickers: List[str] = []

    for t in selected_weights.keys():
        s = fetch_ticker_candles(t, start_date, end_date)
        if not s.empty and len(s) > 10:
            prices_collector[t] = s
        else:
            missing_tickers.append(t)

    # 2. Загрузка бенчмарка IMOEX
    bench_series = fetch_benchmark_candles(start_date, end_date)

if missing_tickers:
    st.sidebar.warning(f"Недостаточно котировок для тикеров: {', '.join(missing_tickers)}. Они исключены из бэктеста.")
    for mt in missing_tickers:
        selected_weights.pop(mt, None)

if len(prices_collector) < 1 or bench_series.empty:
    st.error("Не удалось сформировать исторические ряды котировок для выбранного периода. Попробуйте другой горизонт.")
    st.stop()

# Формируем матрицу цен и выравниваем даты
raw_price_df = pd.DataFrame(prices_collector).dropna()
aligned_dates = raw_price_df.index.intersection(bench_series.index)

if len(aligned_dates) < 20:
    st.error(f"Слишком мало совпадающих торговых дней ({len(aligned_dates)}). Выберите более длительный горизонт.")
    st.stop()

prices_df = raw_price_df.loc[aligned_dates].copy()
bench_df = bench_series.loc[aligned_dates].copy()

# Масштабируем IMOEX к стартовому капиталу
bench_scaled = (bench_df / bench_df.iloc[0]) * initial_capital

# Запуск симуляции портфеля
port_series, fee_series, total_fees = simulate_portfolio(
    prices_df,
    selected_weights,
    initial_capital,
    rebalance_freq=rebalance_freq,
    fee_rate=fee_rate
)

# Линия безрисковой доходности (вклад по ставке ЦБ)
days_from_start = (aligned_dates - aligned_dates[0]).days.values
rf_daily_factor = (1.0 + rf_rate_input / 100.0) ** (days_from_start / 365.25)
rf_series = pd.Series(initial_capital * rf_daily_factor, index=aligned_dates)

# Расчет всех метрик
kpis = calculate_performance_kpis(port_series, bench_scaled, initial_capital, risk_free_rate_pct=rf_rate_input)

# ==========================================
# 4. ВЫВОД РЕЗУЛЬТАТОВ (KPI METRICS)
# ==========================================

m_c1, m_c2, m_c3, m_c4 = st.columns(4)

final_cap = kpis["final_capital"]
profit_rub = final_cap - initial_capital
tot_ret = kpis["total_return_pct"]
bench_ret = kpis["bench_return_pct"]
excess_ret = kpis["alpha_excess_pct"]

m_c1.metric(
    label="Итоговый капитал",
    value=f"{final_cap:,.0f} ₽",
    delta=f"{profit_rub:+,.0f} ₽ ({tot_ret:+.1f}%)"
)

m_c2.metric(
    label="Доходность vs IMOEX",
    value=f"{tot_ret:+.1f}%",
    delta=f"{excess_ret:+.1f}% к рынку" if excess_ret != 0 else "На уровне рынка"
)

m_c3.metric(
    label="CAGR (Годовая доходность)",
    value=f"{kpis['cagr_pct']:+.1f}%",
    delta=f"vs IMOEX {kpis['bench_cagr_pct']:+.1f}%"
)

m_c4.metric(
    label="Макс. просадка (Max DD)",
    value=f"{kpis['max_drawdown_pct']:.1f}%",
    delta=f"vs IMOEX {kpis['bench_max_dd_pct']:.1f}%",
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
    st.caption(f"Период: {aligned_dates[0].strftime('%d.%m.%Y')} — {aligned_dates[-1].strftime('%d.%m.%Y')} ({kpis['trading_days']} торговых дней).")

    display_mode = st.radio("Отображение шкалы:", ["В рублях (Стоимость капитала)", "В процентах доходности (%)"], horizontal=True)

    if display_mode.startswith("В рублях"):
        chart_df = pd.DataFrame({
            "Дата": aligned_dates,
            "Портфель стратегии": port_series.values,
            "Индекс МосБиржи (IMOEX)": bench_scaled.values,
            f"Ставка ЦБ РФ ({rf_rate_input:.1f}%)": rf_series.values
        })
        val_title = "Капитал, ₽"
    else:
        chart_df = pd.DataFrame({
            "Дата": aligned_dates,
            "Портфель стратегии": ((port_series.values / initial_capital) - 1.0) * 100.0,
            "Индекс МосБиржи (IMOEX)": ((bench_scaled.values / initial_capital) - 1.0) * 100.0,
            f"Ставка ЦБ РФ ({rf_rate_input:.1f}%)": ((rf_series.values / initial_capital) - 1.0) * 100.0
        })
        val_title = "Доходность, %"

    melted_chart_df = chart_df.melt(id_vars=["Дата"], var_name="Инструмент", value_name="Значение")

    curve_chart = alt.Chart(melted_chart_df).mark_line().encode(
        x=alt.X("Дата:T", title="Дата"),
        y=alt.Y("Значение:Q", title=val_title),
        color=alt.Color("Инструмент:N", scale=alt.Scale(
            domain=["Портфель стратегии", "Индекс МосБиржи (IMOEX)", f"Ставка ЦБ РФ ({rf_rate_input:.1f}%)"],
            range=["#00E676", "#2979FF", "#FFB300"]
        )),
        strokeWidth=alt.condition(alt.datum.Инструмент == "Портфель стратегии", alt.value(2.8), alt.value(1.8)),
        tooltip=["Дата:T", "Инструмент:N", alt.Tooltip("Значение:Q", format=",.1f")]
    ).properties(height=420).interactive()

    st.altair_chart(curve_chart, width="stretch")

    c_fee1, c_fee2 = st.columns(2)
    with c_fee1:
        st.info(f"💡 **Уплаченные комиссии брокеру:** `{total_fees:,.1f} ₽` (ставка `{broker_fee_pct:.2f}%` при входе и ребалансировках).")
    with c_fee2:
        if excess_ret > 0:
            st.success(f"🚀 **Альфа стратегии:** портфель превзошел рынок на **+{excess_ret:.1f}%** с чистым опережением индекса.")
        else:
            st.warning(f"⚠️ **Отставание от рынка:** портфель уступил индексу IMOEX **{excess_ret:.1f}%**.")

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
        "Просадка IMOEX (%)": bench_dd.values
    })

    dd_melted = dd_df.melt(id_vars=["Дата"], var_name="Индикатор", value_name="Просадка, %")

    dd_chart = alt.Chart(dd_melted).mark_area(opacity=0.35).encode(
        x=alt.X("Дата:T", title="Дата"),
        y=alt.Y("Просадка, %:Q", title="Просадка от пика, %"),
        color=alt.Color("Индикатор:N", scale=alt.Scale(
            domain=["Просадка портфеля (%)", "Просадка IMOEX (%)"],
            range=["#FF1744", "#2979FF"]
        )),
        tooltip=["Дата:T", "Индикатор:N", alt.Tooltip("Просадка, %:Q", format=".2f")]
    ).properties(height=320).interactive()

    st.altair_chart(dd_chart, width="stretch")

    st.markdown("#### 📋 Институциональные коэффициенты риска и устойчивости")
    rk1, rk2, rk3, rk4 = st.columns(4)
    rk1.metric("Sharpe Ratio", f"{kpis['sharpe_ratio']:.2f}", "Норма > 0.5" if kpis['sharpe_ratio'] > 0.5 else "Слабая отдача к риску")
    rk2.metric("Sortino Ratio", f"{kpis['sortino_ratio']:.2f}", "С учетом downside риска")
    rk3.metric("Calmar Ratio", f"{kpis['calmar_ratio']:.2f}", "CAGR / |MaxDD|")
    rk4.metric("Бета к IMOEX", f"{kpis['beta']:.2f}", "Защитный" if kpis['beta'] < 1.0 else "Агрессивнее рынка")

    rk5, rk6, rk7, rk8 = st.columns(4)
    rk5.metric("Волатильность портфеля", f"{kpis['volatility_pct']:.1f}%", f"IMOEX: {kpis['bench_volatility_pct']:.1f}%")
    rk6.metric("Jensen's Alpha", f"{kpis['jensen_alpha_pct']:+.1f}%", "Превышение CAPM модели")
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
