"""Страница детального анализа реального портфеля инвестора с учетом входа в сделки.

Функционал:
1. Загрузка сделок и открытых позиций из izi-invest.ru (по ссылке или username) или отчётов брокера.
2. Анализ средних цен входа (Break-even), нереализованного PnL и долей в портфеле.
3. Таймлайн доходности капитала и сравнение с «Зеркальным IMOEX» (DCA в индекс).
4. Расчёт XIRR (внутренней нормы доходности с учётом пополнений).
5. Анализ закрытых сделок по методу FIFO (Win Rate, срок удержания, доходность).
6. Календарь и аналитика полученных дивидендов и купонов.
7. Быстрый перенос структуры портфеля в модуль стресс-тестирования и бэктеста.
"""

import io
import os
from datetime import datetime
import altair as alt
import numpy as np
import pandas as pd
import streamlit as st

from src.portfolio_importer import (
    calculate_mirror_benchmark_timeline,
    calculate_xirr,
    fetch_izi_invest_data,
    parse_broker_file,
)

# ==========================================
# 1. КОНФИГУРАЦИЯ СТРАНИЦЫ
# ==========================================

st.set_page_config(
    page_title="Реальный Портфель и Сделки | MOEX Helper",
    page_icon="💼",
    layout="wide",
    initial_sidebar_state="expanded"
)

# Инъекция премиальных стилей
st.markdown(
    """
    <style>
    .metric-card {
        background: linear-gradient(135deg, rgba(255,255,255,0.05) 0%, rgba(255,255,255,0.02) 100%);
        border: 1px solid rgba(255,255,255,0.08);
        border-radius: 12px;
        padding: 16px 20px;
        box-shadow: 0 4px 16px rgba(0,0,0,0.25);
    }
    .badge-oil {
        background: rgba(255, 179, 0, 0.15);
        color: #FFB300;
        border: 1px solid rgba(255, 179, 0, 0.3);
        border-radius: 4px;
        padding: 2px 6px;
        font-size: 0.8rem;
    }
    .badge-bank {
        background: rgba(41, 121, 255, 0.15);
        color: #2979FF;
        border: 1px solid rgba(41, 121, 255, 0.3);
        border-radius: 4px;
        padding: 2px 6px;
        font-size: 0.8rem;
    }
    </style>
    """,
    unsafe_allow_html=True
)


# ==========================================
# 2. КЭШИРОВАННАЯ ЗАГРУЗКА ДАННЫХ
# ==========================================

@st.cache_data(ttl=600, show_spinner=False)
def load_portfolio_from_url(url_or_id: str):
    return fetch_izi_invest_data(url_or_id)


# ==========================================
# 3. БОКОВАЯ ПАНЕЛЬ (НАСТРОЙКИ И ИМПОРТ)
# ==========================================

st.sidebar.title("💼 Учёт сделок и Портфель")
st.sidebar.caption("Анализ позиций от реальной цены покупки и история операций.")

DEFAULT_LOCAL_PATH = "/home/silent/Downloads/Ликвидная часть-13.10.2026.xlsx"
has_local_file = os.path.exists(DEFAULT_LOCAL_PATH)

source_options = [
    "🌐 Сервис izi-invest.ru (онлайн)",
    "💻 Локальный файл из Downloads",
    "📂 Загрузить файл через браузер (XLSX / CSV)"
]

source_mode = st.sidebar.radio(
    "Источник данных:",
    options=source_options,
    index=1 if has_local_file else 0
)

portfolio_data = None
load_error = None

if source_mode == "🌐 Сервис izi-invest.ru (онлайн)":
    default_url = "https://izi-invest.ru/maxgamer#sdelki"
    url_input = st.sidebar.text_input(
        "Ссылка на портфель или ID/никнейм:",
        value=default_url,
        help="Публичный портфель izi-invest.ru (например, maxgamer или 47933)."
    )

    col_btn1, col_btn2 = st.sidebar.columns([3, 1])
    with col_btn1:
        load_btn = st.button("🔄 Загрузить портфель", type="primary", width="stretch")
    with col_btn2:
        if st.button("Сброс", width="stretch"):
            st.cache_data.clear()
            st.rerun()

    if url_input:
        with st.spinner("Загрузка данных и истории сделок из izi-invest.ru..."):
            try:
                portfolio_data = load_portfolio_from_url(url_input)
            except Exception as e:
                load_error = str(e)

elif source_mode == "💻 Локальный файл из Downloads":
    local_path = st.sidebar.text_input(
        "Путь к файлу на диске:",
        value=DEFAULT_LOCAL_PATH,
        help="Локальный путь к выгруженному файлу отчета."
    )
    col_btn1, col_btn2 = st.sidebar.columns([3, 1])
    with col_btn1:
        load_local_btn = st.button("🔄 Прочитать файл", type="primary", width="stretch")
    with col_btn2:
        if st.button("Сброс", width="stretch", key="reset_local"):
            st.cache_data.clear()
            st.rerun()

    if local_path and os.path.exists(local_path):
        st.sidebar.success(f"Файл найден: `{os.path.basename(local_path)}` ({os.path.getsize(local_path)/1024:.0f} КБ)")
        with st.spinner("Чтение локального файла и листа 'Сделки'..."):
            try:
                with open(local_path, "rb") as f:
                    file_bytes = f.read()
                portfolio_data = parse_broker_file(file_bytes, os.path.basename(local_path))
            except Exception as e:
                load_error = str(e)
    else:
        load_error = f"Файл не найден по пути: {local_path}"

else:
    uploaded_file = st.sidebar.file_uploader(
        "Загрузите отчет брокера или экспорт izi-invest:",
        type=["xlsx", "xls", "csv"],
        help="Поддерживаются файлы экспорта izi-invest.ru, Snowball, Intelinvest и стандартные CSV со сделками."
    )
    if uploaded_file is not None:
        with st.spinner("Чтение и парсинг файла отчёта..."):
            try:
                file_bytes = uploaded_file.read()
                portfolio_data = parse_broker_file(file_bytes, uploaded_file.name)
            except Exception as e:
                load_error = str(e)

if load_error:
    st.error(f"⚠️ Ошибка загрузки: {load_error}")
    st.info("💡 Убедитесь, что портфель открыт для публичного доступа на izi-invest.ru или файл не повреждён.")
    st.stop()

if not portfolio_data:
    st.info("👈 Нажмите кнопку «Загрузить портфель» в боковой панели или загрузите файл отчёта.")
    st.stop()

summary = portfolio_data["summary"]
df_pos = portfolio_data["positions"].copy()
df_trades = portfolio_data["trades"].copy()
df_fifo = portfolio_data["fifo"].copy()
df_div = portfolio_data["dividends"].copy()
df_coup = portfolio_data["coupons"].copy()

# ==========================================
# 4. ВЕРХНИЙ ДАШБОРД (СВОДНЫЕ МЕТРИКИ)
# ==========================================

st.title("💼 Анализ Реального Портфеля и Сделок")
st.markdown(
    f"Интеграция с источником: **`{portfolio_data.get('identifier', 'izi-invest')}`** &nbsp;|&nbsp; "
    f"Открытых позиций: **{summary['open_positions_count']}** &nbsp;|&nbsp; "
    f"Всего операций в истории: **{summary['total_trades_count']}**"
)

kpi1, kpi2, kpi3, kpi4, kpi5 = st.columns(5)

tot_val = summary["total_value"]
net_inv = summary["net_invested"]
pnl_rub = summary["total_profit_rub"]
pnl_pct = summary["total_profit_pct"]
xirr_pct = summary["xirr_pct"]
pass_income = summary["total_passive_income"]

kpi1.metric(
    label="Текущая стоимость",
    value=f"{tot_val:,.0f} ₽",
    delta=f"{pnl_rub:+,.0f} ₽"
)

kpi2.metric(
    label="Вложено (Net Cash)",
    value=f"{net_inv:,.0f} ₽",
    delta=f"Введено {summary['total_deposits']:,.0f} ₽",
    delta_color="off"
)

kpi3.metric(
    label="Финансовый результат",
    value=f"{pnl_pct:+.2f}%",
    delta=f"{pnl_rub:+,.0f} ₽ PnL"
)

kpi4.metric(
    label="Доходность XIRR",
    value=f"{xirr_pct:+.2f}% годовых",
    delta="С учётом дат довнесений"
)

kpi5.metric(
    label="Дивиденды + Купоны",
    value=f"{pass_income:,.0f} ₽",
    delta=f"Див: {summary['total_dividends']:,.0f} ₽ | Куп: {summary['total_coupons']:,.0f} ₽",
    delta_color="off"
)

st.divider()

# Перенос структуры в Бэктест
col_export_msg, col_export_btn = st.columns([4, 1])
with col_export_msg:
    st.caption("🚀 Хотите проверить устойчивость ваших текущих позиций на исторических кризисах (2020 COVID, 2022 СВО, 2024 ДКП)?")
with col_export_btn:
    if st.button("🧪 Отправить в Бэктест", width="stretch", type="primary"):
        st.session_state["backtest_custom_weights"] = portfolio_data["weights_dict"]
        st.session_state["backtest_custom_capital"] = tot_val
        st.success("Структура скопирована! Перейдите на вкладку «⏳ Бэктест Стратегии» в левом меню.")


# ==========================================
# 5. ТЕМАТИЧЕСКИЕ ВКЛАДКИ
# ==========================================

tab_positions, tab_timeline, tab_trades, tab_fifo, tab_passive = st.tabs([
    "📊 Открытые позиции & Анализ входа",
    "📈 Таймлайн капитала & Зеркальный IMOEX",
    "📑 Журнал всех сделок (Ledger)",
    "🎯 Закрытые сделки (FIFO) & Win Rate",
    "💰 Дивиденды и Купоны"
])


# ------------------------------------------
# ТАБ 1: ОТКРЫТЫЕ ПОЗИЦИИ & АНАЛИЗ ВХОДА
# ------------------------------------------
with tab_positions:
    st.subheader("📊 Текущие активы инвестора и результативность от цен покупки")
    st.caption("Показывает реальную среднюю цену входа (Break-even), текущую цену MOEX, прибыль и долю каждого актива.")

    if not df_pos.empty:
        c_chart1, c_chart2 = st.columns([1, 1])

        with c_chart1:
            st.markdown("##### 🍩 Структура распределения портфеля")
            donut_chart = alt.Chart(df_pos).mark_arc(innerRadius=60).encode(
                theta=alt.Theta(field="Вес, %", type="quantitative"),
                color=alt.Color(field="Тикер", type="nominal", scale=alt.Scale(scheme="tableau20")),
                tooltip=["Тикер", "Название", alt.Tooltip("Текущая стоимость:Q", format=",.0f"), alt.Tooltip("Вес, %:Q", format=".2f")]
            ).properties(height=320)
            st.altair_chart(donut_chart, width="stretch")

        with c_chart2:
            st.markdown("##### 📈 Прибыль / Убыток от точек входа (₽)")
            pnl_bar_chart = alt.Chart(df_pos).mark_bar().encode(
                x=alt.X("Прибыль, ₽:Q", title="Нереализованный PnL (₽)"),
                y=alt.Y("Тикер:N", sort="-x", title="Актив"),
                color=alt.condition(
                    alt.datum["Прибыль, ₽"] >= 0,
                    alt.value("#00E676"),
                    alt.value("#FF1744")
                ),
                tooltip=["Тикер", "Название", alt.Tooltip("Прибыль, ₽:Q", format=",.0f"), alt.Tooltip("Доходность от входа, %:Q", format="+.2f")]
            ).properties(height=320)
            st.altair_chart(pnl_bar_chart, width="stretch")

        # Обогащение позиций фундаментальными тегами
        oil_tickers = {"ROSN", "TRNFP", "SNGS", "SNGSP", "LKOH", "TATN", "TATNP", "NMTP"}
        bank_tickers = {"SBER", "SBERP", "SVCB", "T", "VTBR", "BSPB"}

        df_display = df_pos[[
            "Тикер", "Название", "Количество", "Средняя цена", "Текущая цена",
            "Текущая стоимость", "Вложенная сумма", "Прибыль, ₽", "Доходность от входа, %", "Вес, %"
        ]].copy()

        # Форматирование и подсветка
        st_styled_pos = df_display.style.format({
            "Количество": "{:,.0f}",
            "Средняя цена": "{:,.2f} ₽",
            "Текущая цена": "{:,.2f} ₽",
            "Текущая стоимость": "{:,.0f} ₽",
            "Вложенная сумма": "{:,.0f} ₽",
            "Прибыль, ₽": "{:+,.0f} ₽",
            "Доходность от входа, %": "{:+.2f}%",
            "Вес, %": "{:.2f}%"
        })

        def _color_pnl(val):
            if pd.isna(val) or not isinstance(val, (int, float)):
                return ""
            if val > 0:
                return "color: #00E676; font-weight: bold;"
            elif val < 0:
                return "color: #FF1744; font-weight: bold;"
            return ""

        if hasattr(st_styled_pos, "map"):
            st_styled_pos = st_styled_pos.map(_color_pnl, subset=["Прибыль, ₽", "Доходность от входа, %"])
        elif hasattr(st_styled_pos, "applymap"):
            st_styled_pos = st_styled_pos.applymap(_color_pnl, subset=["Прибыль, ₽", "Доходность от входа, %"])

        st.dataframe(st_styled_pos, width="stretch", hide_index=True)

        # Экспресс-аналитика рисков
        st.markdown("#### 🔍 Аналитический срез портфеля")
        c_an1, c_an2 = st.columns(2)

        with c_an1:
            top_asset = df_pos.iloc[0]
            if top_asset["Вес, %"] > 15.0:
                st.warning(f"⚠️ **Высокая концентрация:** Актив **{top_asset['Тикер']}** занимает **{top_asset['Вес, %']:.1f}%** портфеля. Рекомендуется диверсификация с долей не более 10–15% на эмитента.")
            else:
                st.success("✅ **Хорошая диверсификация:** Ни один эмитент не превышает критическую планку концентрации (>15%).")

        with c_an2:
            oil_holdings = df_pos[df_pos["Тикер"].isin(oil_tickers)]
            if not oil_holdings.empty:
                oil_weight = oil_holdings["Вес, %"].sum()
                st.info(f"🛢️ **Нефтяной и портовый сектор:** суммарная доля составляет **{oil_weight:.1f}%** ({', '.join(oil_holdings['Тикер'].tolist())}). Состояние танкерного флота (TankerMap) и фрахт Magellan оказывают прямое влияние на дивидендную базу этих позиций.")

    else:
        st.info("Нет открытых позиций.")


# ------------------------------------------
# ТАБ 2: ТАЙМЛАЙН КАПИТАЛА & ЗЕРКАЛЬНЫЙ IMOEX
# ------------------------------------------
with tab_timeline:
    st.subheader("📈 Историческая траектория капитала инвестора vs «Зеркальный IMOEX»")
    st.caption("Сравнение фактической динамики портфеля со сценарием: что было бы, если бы те же самые суммы пополнений в те же даты инвестировались в Индекс МосБиржи.")

    timeline_df, bench_ret_pct = calculate_mirror_benchmark_timeline(df_trades, tot_val, bench_symbol="IMOEX")

    if not timeline_df.empty:
        # График сравнения
        timeline_melted = timeline_df.melt(id_vars=["Дата"], var_name="Показатель", value_name="Капитал, ₽")

        line_chart = alt.Chart(timeline_melted).mark_line().encode(
            x=alt.X("Дата:T", title="Дата"),
            y=alt.Y("Капитал, ₽:Q", title="Оценка капитала (₽)"),
            color=alt.Color("Показатель:N", scale=alt.Scale(
                domain=["Вложенный капитал", "Зеркальный IMOEX (₽)"],
                range=["#9E9E9E", "#2979FF"]
            )),
            strokeWidth=alt.condition(alt.datum.Показатель == "Зеркальный IMOEX (₽)", alt.value(2.5), alt.value(1.8)),
            tooltip=["Дата:T", "Показатель:N", alt.Tooltip("Капитал, ₽:Q", format=",.0f")]
        ).properties(height=380).interactive()

        st.altair_chart(line_chart, width="stretch")

        b_c1, b_c2, b_c3 = st.columns(3)
        b_c1.metric("Доходность инвестора (PnL)", f"{pnl_pct:+.2f}%", f"{pnl_rub:+,.0f} ₽ к вложенному")
        b_c2.metric("Доходность Зеркального IMOEX", f"{bench_ret_pct:+.2f}%", "Если бы покупали только Индекс")
        
        alpha_investor = pnl_pct - bench_ret_pct
        if alpha_investor >= 0:
            b_c3.metric("Альфа инвестора", f"{alpha_investor:+.2f}%", "Опережение рынка!")
        else:
            b_c3.metric("Отставание от IMOEX", f"{alpha_investor:+.2f}%", "Уступил пассивному рынку")
    else:
        st.info("Недостаточно данных для построения зеркального бенчмарка.")


# ------------------------------------------
# ТАБ 3: ЖУРНАЛ СДЕЛОК (LEDGER)
# ------------------------------------------
with tab_trades:
    st.subheader("📑 Журнал всех совершённых операций")
    st.caption("Полный хронологический реестр покупок, продаж, дивидендов и перемещений денежных средств.")

    if not df_trades.empty:
        f_c1, f_c2, f_c3 = st.columns(3)
        with f_c1:
            all_tickers = ["Все"] + sorted([t for t in df_trades["Тикер"].dropna().unique() if t])
            selected_ticker = st.selectbox("Фильтр по тикеру:", all_tickers, index=0)
        with f_c2:
            all_ops = ["Все"] + sorted([op for op in df_trades["Операция"].dropna().unique() if op])
            selected_op = st.selectbox("Фильтр по операции:", all_ops, index=0)
        with f_c3:
            search_query = st.text_input("Поиск по названию:", value="")

        filtered_trades = df_trades.copy()
        if selected_ticker != "Все":
            filtered_trades = filtered_trades[filtered_trades["Тикер"] == selected_ticker]
        if selected_op != "Все":
            filtered_trades = filtered_trades[filtered_trades["Операция"] == selected_op]
        if search_query:
            filtered_trades = filtered_trades[filtered_trades["Название"].astype(str).str.contains(search_query, case=False, na=False)]

        st.markdown(f"Найдено записей: **{len(filtered_trades)}** из **{len(df_trades)}**")

        st_styled_trades = filtered_trades.style.format({
            "Дата": lambda d: d.strftime("%Y-%m-%d %H:%M") if pd.notna(d) else "—",
            "Количество": "{:,.2f}",
            "Цена": "{:,.2f} ₽",
            "Сумма": "{:,.2f} ₽",
            "Комиссия, ₽": "{:,.2f} ₽"
        })

        st.dataframe(st_styled_trades, width="stretch", hide_index=True)
    else:
        st.info("История сделок пуста.")


# ------------------------------------------
# ТАБ 4: ЗАКРЫТЫЕ СДЕЛКИ (FIFO) & WIN RATE
# ------------------------------------------
with tab_fifo:
    st.subheader("🎯 Фиксация прибыли и статистика закрытых позиций (FIFO)")
    st.caption("Анализирует сделки, по которым была зафиксирована прибыль или убыток.")

    if not df_fifo.empty:
        total_closed_deals = len(df_fifo)
        wins = df_fifo[df_fifo["Прибыль, ₽"] > 0]
        losses = df_fifo[df_fifo["Прибыль, ₽"] < 0]
        win_rate = (len(wins) / total_closed_deals) * 100.0 if total_closed_deals > 0 else 0.0

        total_realized_profit = df_fifo["Прибыль, ₽"].sum()
        avg_days = df_fifo["Дней в сделке"].mean()

        w_c1, w_c2, w_c3, w_c4 = st.columns(4)
        w_c1.metric("Win Rate закрытых сделок", f"{win_rate:.1f}%", f"{len(wins)} прибыльных / {len(losses)} убыточных")
        w_c2.metric("Зафиксированный PnL", f"{total_realized_profit:+,.0f} ₽", "Суммарный результат")
        w_c3.metric("Средний срок удержания", f"{avg_days:.0f} дней", "Период нахождения в сделке")

        best_deal = df_fifo.sort_values(by="Прибыль, ₽", ascending=False).iloc[0]
        w_c4.metric("Лучшая сделка", f"{best_deal['Тикер']}", f"{best_deal['Прибыль, ₽']:+,.0f} ₽ ({best_deal['Доходность, %']:+.1f}%)")

        st.markdown("##### 📋 Детальный реестр закрытых позиций")
        st_styled_fifo = df_fifo[[
            "Тикер", "Название", "Покупка", "Продажа", "Цена покупки", "Цена продажи",
            "Кол.", "Прибыль, ₽", "Доходность, %", "Дней в сделке", "Доходность годовых, %"
        ]].copy().style.format({
            "Покупка": lambda d: d.strftime("%Y-%m-%d") if pd.notna(d) else "—",
            "Продажа": lambda d: d.strftime("%Y-%m-%d") if pd.notna(d) else "—",
            "Цена покупки": "{:,.2f} ₽",
            "Цена продажи": "{:,.2f} ₽",
            "Кол.": "{:,.0f}",
            "Прибыль, ₽": "{:+,.0f} ₽",
            "Доходность, %": "{:+.2f}%",
            "Дней в сделке": "{:.0f}",
            "Доходность годовых, %": "{:+.2f}%"
        })

        if hasattr(st_styled_fifo, "map"):
            st_styled_fifo = st_styled_fifo.map(_color_pnl, subset=["Прибыль, ₽", "Доходность, %", "Доходность годовых, %"])
        elif hasattr(st_styled_fifo, "applymap"):
            st_styled_fifo = st_styled_fifo.applymap(_color_pnl, subset=["Прибыль, ₽", "Доходность, %", "Доходность годовых, %"])

        st.dataframe(st_styled_fifo, width="stretch", hide_index=True)
    else:
        st.info("В портфеле нет закрытых позиций.")


# ------------------------------------------
# ТАБ 5: ДИВИДЕНДЫ И КУПОНЫ (ПАССИВНЫЙ ДОХОД)
# ------------------------------------------
with tab_passive:
    st.subheader("💰 Анализ пассивного денежного потока")
    st.caption("Хронология фактически зачисленных дивидендов и купонов по годам и эмитентам.")

    # Объединяем выплаты по годам
    div_records = []
    if not df_div.empty:
        for _, r in df_div.iterrows():
            d = r["Дата"]
            amt = float(r["Сумма \nпосле налога"])
            if amt > 0:
                div_records.append({"Дата": d, "Год": d.year, "Тип": "Дивиденды", "Сумма, ₽": amt, "Тикер": r["Тикер"]})

    if not df_coup.empty:
        for _, r in df_coup.iterrows():
            d = r["Дата"]
            amt = float(r["Сумма \nпосле налога"])
            if amt > 0:
                div_records.append({"Дата": d, "Год": d.year, "Тип": "Купоны", "Сумма, ₽": amt, "Тикер": r["Тикер"]})

    if div_records:
        df_payouts = pd.DataFrame(div_records)

        # Агрегация по годам
        yearly_summary = df_payouts.groupby(["Год", "Тип"])["Сумма, ₽"].sum().reset_index()

        bar_div = alt.Chart(yearly_summary).mark_bar().encode(
            x=alt.X("Год:O", title="Год"),
            y=alt.Y("Сумма, ₽:Q", title="Выплаты после налога (₽)"),
            color=alt.Color("Тип:N", scale=alt.Scale(domain=["Дивиденды", "Купоны"], range=["#00E676", "#2979FF"])),
            tooltip=["Год:O", "Тип:N", alt.Tooltip("Сумма, ₽:Q", format=",.0f")]
        ).properties(height=320)

        st.altair_chart(bar_div, width="stretch")

        p_c1, p_c2 = st.columns(2)
        with p_c1:
            st.markdown("##### 📜 Реестр дивидендных выплат")
            if not df_div.empty:
                st.dataframe(
                    df_div[["Дата", "Тикер", "Название", "Кол.", "Дивиденд", "Сумма \nпосле налога"]].head(25),
                    width="stretch",
                    hide_index=True
                )
        with p_c2:
            st.markdown("##### 📜 Реестр купонных выплат")
            if not df_coup.empty:
                st.dataframe(
                    df_coup[["Дата", "Тикер", "Название", "Номинал", "Купон", "Сумма \nпосле налога"]].head(25),
                    width="stretch",
                    hide_index=True
                )
    else:
        st.info("Нет данных о выплатах дивидендов или купонов.")
