import streamlit as st
import os
import pandas as pd
from pathlib import Path

st.set_page_config(
    page_title="Мастер отбора активов | MOEX Helper",
    page_icon="🧭",
    layout="wide",
    initial_sidebar_state="expanded"
)

# =====================================================================
# СТИЛИЗАЦИЯ ИНТЕРФЕЙСА
# =====================================================================
st.markdown("""
<style>
    .step-header-box {
        background: linear-gradient(135deg, rgba(30, 41, 59, 0.7) 0%, rgba(15, 23, 42, 0.9) 100%);
        border: 1px solid rgba(255, 255, 255, 0.12);
        border-radius: 14px;
        padding: 22px 26px;
        margin-bottom: 24px;
        box-shadow: 0 8px 24px rgba(0,0,0,0.25);
    }
    .hud-card {
        background: rgba(255, 255, 255, 0.04);
        border: 1px solid rgba(255, 255, 255, 0.1);
        border-radius: 12px;
        padding: 16px 20px;
        margin-bottom: 15px;
    }
    .step-card {
        background: linear-gradient(135deg, rgba(255,255,255,0.05) 0%, rgba(255,255,255,0.02) 100%);
        border: 1px solid rgba(255,255,255,0.12);
        border-radius: 12px;
        padding: 20px;
        margin-bottom: 20px;
    }
    .step-badge {
        display: inline-block;
        padding: 4px 14px;
        border-radius: 20px;
        font-size: 0.85rem;
        font-weight: 700;
        margin-bottom: 12px;
        text-transform: uppercase;
        letter-spacing: 0.5px;
    }
    .badge-blue { background: rgba(33, 150, 243, 0.2); color: #64B5F6; border: 1px solid rgba(33, 150, 243, 0.4); }
    .badge-green { background: rgba(76, 175, 80, 0.2); color: #81C784; border: 1px solid rgba(76, 175, 80, 0.4); }
    .badge-amber { background: rgba(255, 193, 7, 0.2); color: #FFD54F; border: 1px solid rgba(255, 193, 7, 0.4); }
    .badge-purple { background: rgba(156, 39, 176, 0.2); color: #BA68C8; border: 1px solid rgba(156, 39, 176, 0.4); }
    .ticker-chip {
        display: inline-block;
        background: rgba(59, 130, 246, 0.2);
        border: 1px solid rgba(96, 165, 250, 0.4);
        color: #93C5FD;
        padding: 4px 10px;
        border-radius: 6px;
        font-weight: 600;
        margin-right: 6px;
        margin-bottom: 6px;
    }
</style>
""", unsafe_allow_html=True)

# =====================================================================
# СПРАВОЧНИКИ И СЕКТОРЫ
# =====================================================================
BANK_TICKERS     = ['SBER', 'SBERP', 'VTBR', 'TCSG', 'BSPB', 'CBOM', 'T', 'SVCB']
IT_TICKERS       = ['ASTR', 'POSI', 'DIAS', 'DATA', 'SOFL', 'VKCO', 'YNDX', 'HEAD', 'OZON']
OIL_TICKERS      = ['ROSN', 'LKOH', 'SIBN', 'TATN', 'TATNP', 'SNGS', 'SNGSP', 'TRNFP', 'BANE', 'BANEP', 'RNFT']
STEEL_TICKERS    = ['CHMF', 'NLMK', 'MAGN']
GOLD_TICKERS     = ['PLZL', 'UGC', 'SELG']
CONSUMER_TICKERS = ['MGNT', 'FIVE', 'FIXP', 'OBUV', 'ORUP', 'BELU', 'AQUA']
TELECOM_TICKERS  = ['MTSS', 'RTKM', 'RTKMP']
UTILITIES_TICKERS = ['IRAO', 'UPRO', 'HYDR', 'MSNG', 'FEES', 'LSNG', 'LSNGP']
CYCLICAL_TICKERS = ['CHMF', 'NLMK', 'MAGN', 'ALRS', 'PLZL', 'UGC', 'MTLR', 'RASP', 'SELG']
HOLDING_TICKERS  = ['SNGS', 'SNGSP', 'AFKS', 'SFIN', 'ENPG', 'GAZP']
ZERO_DEBT_TICKERS = ['SNGS', 'SNGSP']
TOXIC_TICKERS    = ['PIKK', 'SMLT', 'EUTR', 'QIWI', 'POLY', 'ORUP', 'OBUV', 'RUGR', 'FIXP', 'CBOM']

COMPANY_NAMES = {
    "SBER": "Сбербанк",
    "SBERP": "Сбербанк (преф)",
    "LKOH": "ЛУКОЙЛ",
    "GAZP": "Газпром",
    "ROSN": "Роснефть",
    "NVTK": "НОВАТЭК",
    "GMKN": "ГМК Норильский никель",
    "CHMF": "Северсталь",
    "NLMK": "НЛМК",
    "MAGN": "ММК",
    "PLZL": "Полюс Золото",
    "MGNT": "Магнит",
    "BELU": "НоваБев Групп (Белуга)",
    "T": "Т-Банк (ТКС Холдинг)",
    "TATN": "Татнефть",
    "TATNP": "Татнефть (преф)",
    "SNGS": "Сургутнефтегаз",
    "SNGSP": "Сургутнефтегаз (преф)",
    "TRNFP": "Транснефть (преф)",
    "YNDX": "Яндекс",
    "ASTR": "Группа Астра",
    "POSI": "Позитив Текнолоджиз",
    "HEAD": "Хэдхантер",
    "OZON": "Озон",
    "DIAS": "Диасофт",
    "SOFL": "Софтлайн",
    "VKCO": "ВК",
    "IRAO": "Интер РАО",
    "UPRO": "Юнипро",
    "HYDR": "РусГидро",
    "FEES": "Россети",
    "BSPB": "Банк Санкт-Петербург",
    "VTBR": "ВТБ",
    "SVCB": "Совкомбанк",
    "MTSS": "МТС",
    "RTKM": "Ростелеком",
    "ALRS": "АЛРОСА",
    "FLOT": "Совкомфлот",
    "NMTP": "НМТП",
    "MDMG": "Мать и дитя",
    "AQUA": "Инарктика",
    "AFKS": "АФК Система",
    "AFLT": "Аэрофлот",
    "UGC": "Южуралзолото",
    "SELG": "Селигдар",
    "CBOM": "МКБ",
    "PIKK": "ПИК",
    "SMLT": "Самолет",
    "EUTR": "ЕвроТранс",
    "DOMRF": "Дом.РФ",
    "CNRU": "Циан",
    "IVAT": "Ива"
}

def get_sector(ticker: str) -> str:
    if ticker in BANK_TICKERS: return 'Финансы / Банки'
    if ticker in OIL_TICKERS: return 'Нефть и Газ'
    if ticker in IT_TICKERS: return 'IT / Финтех'
    if ticker in STEEL_TICKERS: return 'Металлургия'
    if ticker in GOLD_TICKERS: return 'Золотодобыча'
    if ticker in CONSUMER_TICKERS: return 'Потребительский'
    if ticker in TELECOM_TICKERS: return 'Телеком'
    if ticker in UTILITIES_TICKERS: return 'Энергетика'
    return 'Широкий рынок'

# =====================================================================
# ИНИЦИАЛИЗАЦИЯ СОСТОЯНИЯ (SESSION STATE)
# =====================================================================
if "wizard_basket" not in st.session_state:
    st.session_state["wizard_basket"] = ["SBER", "LKOH", "BELU"]

if "wizard_sentiment_flags" not in st.session_state:
    st.session_state["wizard_sentiment_flags"] = {"SBER": True, "LKOH": True, "BELU": True}

if "wizard_notes" not in st.session_state:
    st.session_state["wizard_notes"] = {
        "SBER": "Стабильный дивидендный кэшфлоу, ROE > 22%, чистая прибыль рекордная",
        "LKOH": "Отрицательный чистый долг, защита от девальвации, байбэк",
        "BELU": "Высокая отдача на капитал ROE > 23%, дивиденды 3 раза в год"
    }

if "wizard_capital" not in st.session_state:
    st.session_state["wizard_capital"] = 100000

if "wizard_max_share" not in st.session_state:
    st.session_state["wizard_max_share"] = 12

if "wizard_min_roe" not in st.session_state:
    st.session_state["wizard_min_roe"] = 15

if "wizard_max_debt" not in st.session_state:
    st.session_state["wizard_max_debt"] = 1.5

# =====================================================================
# ЗАГРУЗКА И РАСЧЕТ HEALTH SCORE
# =====================================================================
@st.cache_data(ttl=3600)
def load_screener_data():
    cache_path = Path(os.path.abspath(__file__)).parent.parent / "fundamentals_cache.csv"
    if not cache_path.exists():
        return pd.DataFrame()
    
    try:
        df = pd.read_csv(cache_path)
    except Exception:
        return pd.DataFrame()
    
    df['ROE_%'] = df['ROE_%'].fillna(0.0)
    df['Debt_EBITDA'] = df['Debt_EBITDA'].fillna(1.0)
    df['Rev_Growth_%'] = df['Rev_Growth_%'].fillna(0.0)
    df['P_BV'] = df['P_BV'].fillna(1.0)
    df['P_E'] = df['P_E'].fillna(10.0)

    # Нормализация
    df['ROE_norm'] = df['ROE_%'].clip(upper=40.0)
    df.loc[df['ticker'].isin(IT_TICKERS) & (df['ROE_norm'] <= 0), 'ROE_norm'] = 30.0

    growth_mult = 1 + (df['Rev_Growth_%'].clip(lower=-50, upper=100) / 100.0)
    safe_debt = df['Debt_EBITDA'].clip(lower=-0.5)

    # Базовый расчет Health Score
    df['Health_Score'] = (((df['ROE_norm'] / df['P_E'].clip(lower=0.5)) / (1 + safe_debt)) * growth_mult).round(2)

    # Холдинги
    is_holding = df['ticker'].isin(HOLDING_TICKERS)
    df.loc[is_holding, 'Health_Score'] = (((3.0 / df.loc[is_holding, 'P_BV'].clip(lower=0.1)) / (1 + safe_debt[is_holding])) * growth_mult[is_holding]).round(2)

    # Банки
    is_bank = df['ticker'].isin(BANK_TICKERS)
    df.loc[is_bank, 'Health_Score'] = (((df.loc[is_bank, 'ROE_norm'] / (df.loc[is_bank, 'P_BV'].clip(lower=0.1) * 5.0)) / (1 + safe_debt[is_bank])) * growth_mult[is_bank]).round(2)

    # Дополнительные поля
    df['Сектор'] = df['ticker'].apply(get_sector)
    df['Компания'] = df['ticker'].apply(lambda t: COMPANY_NAMES.get(t, t))
    df['Токсичный'] = df['ticker'].isin(TOXIC_TICKERS)

    return df

screener_df = load_screener_data()

# =====================================================================
# ШАПКА СТРАНИЦЫ И ПОСТОЯННЫЙ ТРЕКЕР (BASKET HUD)
# =====================================================================
st.markdown("""
<div class="step-header-box">
    <h1 style="margin:0; font-size: 2.1rem; color: #F8FAFC;">🧭 Мастер отбора активов (Инвестиционный пайплайн)</h1>
    <p style="margin: 8px 0 0 0; color: #94A3B8; font-size: 1.05rem;">
        Пошаговый сквозной алгоритм отбора акций на MOEX. Следуйте этапам цепочки, отбирайте активы в корзину сделок и рассчитывайте доли и транши без необходимости держать в голове формулы и риск-правила.
    </p>
</div>
""", unsafe_allow_html=True)

# Верхняя плашка: Активная корзина и статус
current_basket = st.session_state["wizard_basket"]
checked_cnt = sum(1 for t in current_basket if st.session_state["wizard_sentiment_flags"].get(t, False))

with st.container(border=True):
    h_col1, h_col2, h_col3, h_col4 = st.columns([3, 1.2, 1.2, 1.6])
    with h_col1:
        st.markdown("**🛒 Ваша активная корзина отбора:**")
        if current_basket:
            chips_html = "".join([f'<span class="ticker-chip">🟢 {t} ({COMPANY_NAMES.get(t, t)})</span>' for t in current_basket])
            st.markdown(chips_html, unsafe_allow_html=True)
        else:
            st.caption("Корзина пуста. Добавьте бумаги на Шаге 2 (Скрининг).")

    with h_col2:
        st.metric("Бумаг в корзине", f"{len(current_basket)} шт.")

    with h_col3:
        st.metric("Аудит рисков", f"{checked_cnt}/{len(current_basket) if current_basket else 0} пройдено")

    with h_col4:
        st.write("")
        c_reset1, c_reset2 = st.columns(2)
        with c_reset1:
            if st.button("🔄 Топ-3", help="Загрузить проверенную сбалансированную корзину (Сбер, Лукойл, НоваБев)"):
                st.session_state["wizard_basket"] = ["SBER", "LKOH", "BELU"]
                st.session_state["wizard_sentiment_flags"] = {"SBER": True, "LKOH": True, "BELU": True}
                st.rerun()
        with c_reset2:
            if st.button("🗑️ Сброс", help="Очистить корзину для создания нового набора"):
                st.session_state["wizard_basket"] = []
                st.session_state["wizard_sentiment_flags"] = {}
                st.rerun()

st.write("")

# =====================================================================
# 5 ШАГОВ АЛГОРИТМА (TABS WIZARD)
# =====================================================================
tab1, tab2, tab3, tab4, tab5 = st.tabs([
    "1. 🌍 Макро-фильтр",
    "2. 📊 Фундаментальный скринер",
    "3. 💬 Сентимент & Аудит рисков",
    "4. ⚖️ Расчет долей и Лимиты",
    "5. 🚀 План входа (DCA Лесенка)"
])

# ---------------------------------------------------------------------
# ТАБ 1: МАКРО-ФАЗА
# ---------------------------------------------------------------------
with tab1:
    st.markdown("""
    <div class="step-card">
        <span class="step-badge badge-blue">ЭТАП 1: МАКРОЭКОНОМИЧЕСКИЙ КОНТЕКСТ</span>
        <h3 style="margin-top:0;">🌍 Какая фаза рынка сейчас? Настройка фокуса</h3>
        <p style="margin-bottom:0; color:#CBD5E1;">
            Разные компании ведут себя по-разному в зависимости от ключевой ставки ЦБ РФ и инфляции. При высокой ставке (выше 15–20%) компании с долгами отдают до 100% прибыли на кредитные проценты, а компании с кубышкой получают дополнительный процентный доход.
        </p>
    </div>
    """, unsafe_allow_html=True)

    m_col1, m_col2 = st.columns([1.8, 1.2])

    with m_col1:
        macro_phase = st.radio(
            "Выберите текущий режим экономики РФ:",
            [
                "🧊 1. Стагфляция / Жесткая ДКП (Высокая ставка 16–21%+, инфляция) [АКТУАЛЬНО СЕЙЧАС]",
                "📉 2. Рецессия / Смягчение ДКП (Цикл снижения ключевой ставки ЦБ)",
                "🚀 3. Восстановление и Перегрев (Низкая ставка, бурный рост кредитования)"
            ],
            index=0
        )

        if "1. Стагфляция" in macro_phase:
            st.info("""
            **🎯 Рекомендации алгоритма для текущей фазы:**
            * **Кого отбираем:** Компании с отрицательным чистым долгом (кубышкой), высокой эффективностью капитала (`ROE > 18%`) и устойчивым кэшфлоу.
            * **Сектора-фавориты:** Банки с запасом капитала по нормативу Н1.0 (`SBER`, `T`), экспортеры без валютных долгов (`LKOH`, `SNGSP`), потребительский сектор первой необходимости (`MGNT`, `BELU`).
            * **Кого исключаем:** Закредитованных девелоперов, компании с плавающим кредитным долгом выше 2.0x EBITDA.
            """)
            rec_roe = 15
            rec_debt = 1.5
        elif "2. Рецессия" in macro_phase:
            st.info("""
            **🎯 Рекомендации алгоритма:**
            * **Кого отбираем:** Длинные ОФЗ (фиксация рекордной доходности), акции роста IT и финтеха (`YNDX`, `ASTR`, `HEAD`).
            * **Сектора-фавориты:** IT-сектор, телекомы, дивидендные аристократы.
            """)
            rec_roe = 12
            rec_debt = 2.2
        else:
            st.info("""
            **🎯 Рекомендации алгоритма:**
            * **Кого отбираем:** Цикличные сырьевые гиганты, металлургия, строители.
            * **Сектора-фавориты:** `CHMF`, `NLMK`, `MAGN`, `PIKK`, `SMLT`.
            """)
            rec_roe = 10
            rec_debt = 2.5

    with m_col2:
        with st.container(border=True):
            st.markdown("#### ⚙️ Авто-адаптация скринера")
            st.write(f"Рекомендуемый фильтр ROE: **≥ {rec_roe}%**")
            st.write(f"Рекомендуемый лимит долга Debt/EBITDA: **≤ {rec_debt}x**")
            
            if st.button("⚡ Применить к Скринеру (Шаг 2)", use_container_width=True):
                st.session_state["wizard_min_roe"] = rec_roe
                st.session_state["wizard_max_debt"] = rec_debt
                st.success("✅ Параметры применены! Переходите на вкладку «2. Фундаментальный скринер».")

            st.divider()
            try:
                st.page_link("streamlit_project.py", label="Открыть Макро-часы на Главной", icon="📈")
            except Exception:
                pass

# ---------------------------------------------------------------------
# ТАБ 2: ФУНДАМЕНТАЛЬНЫЙ СКРИНИНГ
# ---------------------------------------------------------------------
with tab2:
    st.markdown("""
    <div class="step-card">
        <span class="step-badge badge-green">ЭТАП 2: ФУНДАМЕНТАЛЬНЫЙ СКРИНИНГ</span>
        <h3 style="margin-top:0;">📊 Отбор надежных компаний по рейтингу Health Score</h3>
        <p style="margin-bottom:0; color:#CBD5E1;">
            Отфильтруйте более 60 акций Мосбиржи по финансовой устойчивости. Рейтинг Health Score объединяет рентабельность ROE, дешевизну P/E, штраф за долг и премию за рост выручки.
        </p>
    </div>
    """, unsafe_allow_html=True)

    if screener_df.empty:
        st.error("Файл fundamentals_cache.csv не найден. Запустите парсер данных.")
    else:
        # Панель фильтров
        f_col1, f_col2, f_col3, f_col4 = st.columns([1.5, 1.5, 2, 1.5])
        with f_col1:
            flt_roe = st.slider("Минимальный ROE (%):", 0, 35, int(st.session_state["wizard_min_roe"]), 1)
        with f_col2:
            flt_debt = st.slider("Макс. Debt / EBITDA:", 0.5, 4.0, float(st.session_state["wizard_max_debt"]), 0.1)
        with f_col3:
            all_sectors = sorted(screener_df['Сектор'].unique().tolist())
            flt_sectors = st.multiselect("Секторы:", options=all_sectors, default=all_sectors)
        with f_col4:
            st.write("")
            flt_toxic = st.checkbox("Исключить карантин", value=True, help="Отсекает предбанкротов и токсичные бумаги (PIKK, SMLT, EUTR, CBOM и др.)")

        # Применение фильтров
        filtered = screener_df.copy()
        filtered = filtered[filtered['ROE_%'] >= flt_roe]
        filtered = filtered[filtered['Debt_EBITDA'] <= flt_debt]
        if flt_sectors:
            filtered = filtered[filtered['Сектор'].isin(flt_sectors)]
        if flt_toxic:
            filtered = filtered[~filtered['Токсичный']]

        filtered = filtered.sort_values(by="Health_Score", ascending=False).reset_index(drop=True)

        st.caption(f"Найдено подходящих компаний: **{len(filtered)}** из {len(screener_df)}")

        # Таблица результатов
        display_df = filtered[['ticker', 'Компания', 'Сектор', 'Health_Score', 'ROE_%', 'P_E', 'Debt_EBITDA', 'Rev_Growth_%', 'Div_RUB']].copy()
        display_df.columns = ['Тикер', 'Компания', 'Сектор', 'Health Score', 'ROE %', 'P/E', 'Debt/EBITDA', 'Рост выручки %', 'Дивиденд ₽']

        st.dataframe(
            display_df,
            column_config={
                "Health Score": st.column_config.NumberColumn("Health Score", format="%.2f", help="Комплексный балл здоровья эмитента (чем выше, тем надежнее)"),
                "ROE %": st.column_config.NumberColumn("ROE %", format="%.1f%%"),
                "P/E": st.column_config.NumberColumn("P/E", format="%.1f"),
                "Debt/EBITDA": st.column_config.NumberColumn("Debt/EBITDA", format="%.2f"),
                "Рост выручки %": st.column_config.NumberColumn("Рост выручки %", format="%.1f%%"),
                "Дивиденд ₽": st.column_config.NumberColumn("Дивиденд ₽", format="%.2f ₽"),
            },
            use_container_width=True,
            height=320
        )

        st.divider()

        # Блок интерактивного выбора в корзину
        st.subheader("🎯 Добавление отобранных бумаг в корзину сделки")
        
        c_pick1, c_pick2 = st.columns([3, 1.2])
        with c_pick1:
            all_available_tickers = screener_df['ticker'].tolist()
            new_selection = st.multiselect(
                "Выберите акции, которые войдут в вашу корзину сделок:",
                options=all_available_tickers,
                default=[t for t in st.session_state["wizard_basket"] if t in all_available_tickers],
                format_func=lambda x: f"{x} — {COMPANY_NAMES.get(x, x)}"
            )
            if new_selection != st.session_state["wizard_basket"]:
                st.session_state["wizard_basket"] = new_selection
                for t in new_selection:
                    if t not in st.session_state["wizard_sentiment_flags"]:
                        st.session_state["wizard_sentiment_flags"][t] = False
                st.rerun()

        with c_pick2:
            st.write("")
            top_3 = filtered['ticker'].head(3).tolist()
            if st.button(f"⚡ Взять Топ-3 ({', '.join(top_3)})", use_container_width=True):
                st.session_state["wizard_basket"] = top_3
                for t in top_3:
                    st.session_state["wizard_sentiment_flags"][t] = True
                st.rerun()

            top_5 = filtered['ticker'].head(5).tolist()
            if st.button(f"⚡ Взять Топ-5", use_container_width=True):
                st.session_state["wizard_basket"] = top_5
                for t in top_5:
                    st.session_state["wizard_sentiment_flags"][t] = True
                st.rerun()

# ---------------------------------------------------------------------
# ТАБ 3: СЕНТИМЕНТ И АУДИТ РИСКОВ
# ---------------------------------------------------------------------
with tab3:
    st.markdown("""
    <div class="step-card">
        <span class="step-badge badge-amber">ЭТАП 3: КАЧЕСТВЕННЫЙ АУДИТ И СЕНТИМЕНТ</span>
        <h3 style="margin-top:0;">💬 Защита от скрытых рисков (Новости, Пульс, Smart-Lab, AI)</h3>
        <p style="margin-bottom:0; color:#CBD5E1;">
            Фундаментальные мультипликаторы смотрят в прошлое. Сентимент и анализ инфополя защищают вас от непредвиденных новостей: судебных исков, внезапных допэмиссий (SPO), срывов дивидендов и санкционных ограничений.
        </p>
    </div>
    """, unsafe_allow_html=True)

    if not current_basket:
        st.warning("⚠️ В вашей корзине пока нет бумаг. Вернитесь на вкладку «2. Фундаментальный скринер» и выберите 2–5 тикеров.")
    else:
        st.markdown(f"**Проверка кандидатов в корзине ({len(current_basket)} шт.):**")
        
        for ticker in current_basket:
            c_name = COMPANY_NAMES.get(ticker, ticker)
            sector = get_sector(ticker)
            is_checked = st.session_state["wizard_sentiment_flags"].get(ticker, False)
            current_note = st.session_state["wizard_notes"].get(ticker, "")

            with st.container(border=True):
                col_info, col_link, col_check = st.columns([2.5, 2, 2.5])
                with col_info:
                    status_icon = "🟢" if is_checked else "⚪"
                    st.markdown(f"### {status_icon} **{ticker}** — {c_name}")
                    st.caption(f"Сектор: **{sector}**")

                with col_link:
                    st.write("")
                    try:
                        st.page_link(
                            "pages/2_💬_Сентимент_и_Пульс.py",
                            label=f"Открыть Сентимент {ticker} ↗",
                            icon="💬"
                        )
                    except Exception:
                        pass
                    st.caption("Проверьте драйверы и риски в Пульсе")

                with col_check:
                    st.write("")
                    new_val = st.checkbox(
                        f"✅ Рисков нет (подтвердить {ticker})",
                        value=is_checked,
                        key=f"chk_sent_{ticker}",
                        help="Отметьте, если в новостях и AI-отчете нет сообщений о банкротстве, срыве дивидендов или судах"
                    )
                    if new_val != is_checked:
                        st.session_state["wizard_sentiment_flags"][ticker] = new_val
                        st.rerun()

                # Поле для заметок
                note_val = st.text_input(
                    f"📝 Заметка инвестора по {ticker}:",
                    value=current_note,
                    key=f"note_input_{ticker}",
                    placeholder="Например: Сильный квартальный отчет, ждем рекомендацию СД по дивидендам..."
                )
                if note_val != current_note:
                    st.session_state["wizard_notes"][ticker] = note_val

        st.divider()
        checked_total = sum(1 for t in current_basket if st.session_state["wizard_sentiment_flags"].get(t, False))
        if checked_total == len(current_basket):
            st.success(f"🎉 Отлично! Все {len(current_basket)} бумаг прошли качественную проверку без красных флагов.")
        else:
            st.warning(f"⚠️ Проверено {checked_total} из {len(current_basket)} бумаг. Завершите проверку перед покупкой.")

# ---------------------------------------------------------------------
# ТАБ 4: РАСЧЕТ ДОЛЕЙ И ЛИМИТЫ РИСКА
# ---------------------------------------------------------------------
with tab4:
    st.markdown("""
    <div class="step-card">
        <span class="step-badge badge-purple">ЭТАП 4: РАСЧЕТ ДОЛЕЙ И РИСК-ЛИМИТ</span>
        <h3 style="margin-top:0;">⚖️ Математический мани-менеджмент (Position Sizing)</h3>
        <p style="margin-bottom:0; color:#CBD5E1;">
            Никогда не ставьте всё на одну карту. Золотое правило инвестиций на Московской Бирже — ограничение максимального веса одной акции на уровне 10–12%. Это гарантирует, что даже форс-мажор в одной компании не разрушит ваш капитал.
        </p>
    </div>
    """, unsafe_allow_html=True)

    if not current_basket:
        st.warning("⚠️ Корзина пуста. Сначала отберите бумаги на Шаге 2.")
    else:
        p_col1, p_col2 = st.columns([1.5, 2.5])
        with p_col1:
            capital_input = st.number_input(
                "Сумма инвестиций в эту сделку (₽):",
                min_value=10000,
                max_value=50000000,
                value=int(st.session_state["wizard_capital"]),
                step=10000
            )
            st.session_state["wizard_capital"] = capital_input

            max_limit_pct = st.slider(
                "Лимит на одну акцию (%):",
                min_value=5,
                max_value=30,
                value=int(st.session_state["wizard_max_share"]),
                step=1,
                help="Рекомендуется 10–12% для снижения несистематического риска"
            )
            st.session_state["wizard_max_share"] = max_limit_pct

            weight_mode = st.radio(
                "Алгоритм распределения весов:",
                ["Взвешивание по Health Score (больше надежным)", "Равными долями (Equal Weight)"]
            )

        with p_col2:
            # Расчет весов
            basket_data = []
            for t in current_basket:
                row = screener_df[screener_df['ticker'] == t]
                h_score = float(row['Health_Score'].iloc[0]) if not row.empty else 1.0
                basket_data.append({"ticker": t, "name": COMPANY_NAMES.get(t, t), "score": max(h_score, 0.1)})

            df_weights = pd.DataFrame(basket_data)
            n_items = len(df_weights)

            if "Health Score" in weight_mode:
                total_score = df_weights['score'].sum()
                raw_weights = (df_weights['score'] / total_score) * 100.0
            else:
                raw_weights = pd.Series([100.0 / n_items] * n_items)

            # Обрезка по лимиту (Capping)
            capped_weights = raw_weights.clip(upper=float(max_limit_pct))
            allocated_pct = capped_weights.sum()
            cash_buffer_pct = max(0.0, 100.0 - allocated_pct)

            df_weights['Вес (%)'] = capped_weights.round(1)
            df_weights['Сумма (₽)'] = ((df_weights['Вес (%)'] / 100.0) * capital_input).round(0)

            st.markdown(f"#### 💼 Расчет корзины на {capital_input:,.0f} ₽".replace(",", " "))
            
            # Таблица распределения
            disp_weights = df_weights[['ticker', 'name', 'Вес (%)', 'Сумма (₽)']].copy()
            disp_weights.columns = ['Тикер', 'Эмитент', 'Вес (%)', 'Сумма покупки (₽)']

            st.dataframe(
                disp_weights,
                column_config={
                    "Вес (%)": st.column_config.NumberColumn("Вес (%)", format="%.1f%%"),
                    "Сумма покупки (₽)": st.column_config.NumberColumn("Сумма покупки (₽)", format="%.0f ₽"),
                },
                use_container_width=True
            )

            if cash_buffer_pct > 0.1:
                st.info(
                    f"🛡️ **Защитная подушка (Фонд ликвидности LQDT / ОФЗ): {cash_buffer_pct:.1f}% ({cash_buffer_pct/100*capital_input:,.0f} ₽)**\n"
                    f"Так как был применен лимит безопасности ({max_limit_pct}% на бумагу), остаток средств рекомендуется разместить в фонд ликвидности до появления новых идей."
                )

# ---------------------------------------------------------------------
# ТАБ 5: ПЛАН ВХОДА (DCA ЛЕСЕНКА)
# ---------------------------------------------------------------------
with tab5:
    st.markdown("""
    <div class="step-card">
        <span class="step-badge badge-green">ЭТАП 5: ИСПОЛНЕНИЕ И УЧЕТ СДЕЛКИ</span>
        <h3 style="margin-top:0;">🚀 Дисциплинированный вход лесенкой (DCA)</h3>
        <p style="margin-bottom:0; color:#CBD5E1;">
            Покупка на 100% объема в один день — частая ошибка. Рынок акций MOEX волатилен. Разделение позиции на 3 транша защищает от локальных просадок и дает лучшую среднюю цену входа.
        </p>
    </div>
    """, unsafe_allow_html=True)

    if not current_basket:
        st.warning("⚠️ Корзина пуста. Сначала сформируйте корзину.")
    else:
        st.markdown("#### 🪜 Таблица 3 траншей для исполнения в терминале брокера")
        
        # Генерация траншей: 40% - 30% - 30%
        dca_rows = []
        for _, row in df_weights.iterrows():
            t_sum = row['Сумма (₽)']
            tranche_1 = round(t_sum * 0.40)
            tranche_2 = round(t_sum * 0.30)
            tranche_3 = round(t_sum * 0.30)
            dca_rows.append({
                "Тикер": row['ticker'],
                "Эмитент": row['name'],
                "Общий объем (₽)": t_sum,
                "Транш 1 (Сегодня, 40%)": tranche_1,
                "Транш 2 (Коррекция -3%, 30%)": tranche_2,
                "Транш 3 (Тренд, 30%)": tranche_3
            })

        df_dca = pd.DataFrame(dca_rows)

        st.dataframe(
            df_dca,
            column_config={
                "Общий объем (₽)": st.column_config.NumberColumn("Итого (₽)", format="%.0f ₽"),
                "Транш 1 (Сегодня, 40%)": st.column_config.NumberColumn("Транш 1 (40%)", format="%.0f ₽"),
                "Транш 2 (Коррекция -3%, 30%)": st.column_config.NumberColumn("Транш 2 (30%)", format="%.0f ₽"),
                "Транш 3 (Тренд, 30%)": st.column_config.NumberColumn("Транш 3 (30%)", format="%.0f ₽"),
            },
            use_container_width=True
        )

        st.divider()

        # Форматированный торговый план для копирования
        st.subheader("📋 Готовая шпаргалка для отправки заявки брокеру")
        
        plan_text = f"=== ТОРГОВЫЙ ПЛАН MOEX HELPER ===\n"
        plan_text += f"Дата формирования: {pd.Timestamp.now().strftime('%Y-%m-%d %H:%M')}\n"
        plan_text += f"Сумма инвестиций: {capital_input:,.0f} ₽\n"
        plan_text += f"Макс. лимит на актив: {max_limit_pct}%\n\n"
        plan_text += f"ОРДЕРА ПО ТРАНШАМ:\n"
        for _, r in df_dca.iterrows():
            note = st.session_state['wizard_notes'].get(r['Тикер'], '')
            plan_text += f"• {r['Тикер']} ({r['Эмитент']}): Всего {r['Общий объем (₽)']:,.0f} ₽\n"
            plan_text += f"   - Транш 1 (Рыночный ордер): {r['Транш 1 (Сегодня, 40%)']:,.0f} ₽\n"
            plan_text += f"   - Транш 2 (Лимитный ордер -3%): {r['Транш 2 (Коррекция -3%, 30%)']:,.0f} ₽\n"
            plan_text += f"   - Транш 3 (По тренду через месяц): {r['Транш 3 (Тренд, 30%)']:,.0f} ₽\n"
            if note:
                plan_text += f"   - Тезис: {note}\n"
        if cash_buffer_pct > 0.1:
            plan_text += f"\n• ЗАЩИТНАЯ ПОДУШКА (LQDT/ОФЗ): {cash_buffer_pct/100*capital_input:,.0f} ₽ ({cash_buffer_pct:.1f}%)\n"

        st.code(plan_text, language="text")

        # Навигация к остальным модулям
        nav1, nav2 = st.columns(2)
        with nav1:
            try:
                st.page_link("pages/3_⏳_Бэктест_Стратегии.py", label="⏳ Стресс-тест корзины на истории (Бэктест)", icon="⏳")
            except Exception:
                pass
        with nav2:
            try:
                st.page_link("pages/4_💼_Реальный_Портфель_и_Сделки.py", label="💼 Учет купленных позиций и мониторинг XIRR", icon="💼")
            except Exception:
                pass

st.divider()

# =====================================================================
# ИТОГОВЫЙ ИНДИКАТОР ГОТОВНОСТИ СДЕЛКИ (DEAL READINESS HUD)
# =====================================================================
st.subheader("🏁 Итоговая готовность сделки к исполнению (Deal Readiness)")

chk_macro = True
chk_assets = len(current_basket) >= 2
chk_sentiment = (checked_cnt == len(current_basket)) and (len(current_basket) > 0)
chk_limit = max_limit_pct <= 15
chk_dca = len(current_basket) > 0

checklist_items = [
    ("1. Макро-фаза выбрана и учтена", chk_macro),
    ("2. Отобрано от 2 до 8 бумаг с высоким Health Score", chk_assets),
    ("3. Сентимент всех отобранных бумаг проверен (без красных флагов)", chk_sentiment),
    ("4. Соблюден лимит риска (≤12-15% на акцию)", chk_limit),
    ("5. Рассчитан 3-траншевый план входа лесенкой (DCA)", chk_dca)
]

score_val = sum(1 for _, val in checklist_items if val)
pct_val = score_val / 5.0

hud_c1, hud_c2 = st.columns([1.5, 2.5])
with hud_c1:
    st.markdown(f"**Прогресс выполнения цепочки: {score_val} из 5**")
    st.progress(pct_val)
    if score_val == 5:
        st.success("🟢 **ГОТОВО К ИСПОЛНЕНИЮ:** вся цепочка проверок пройдена, риск оцифрован, ордера рассчитаны.")
    elif score_val >= 3:
        st.warning("🟡 **УМЕРЕННАЯ ГОТОВНОСТЬ:** завершите проверку оставшихся пунктов перед отправкой ордеров.")
    else:
        st.error("🔴 **НЕ ГОТОВО:** пройдите шаги алгоритма для защиты капитала.")

with hud_c2:
    for label, val in checklist_items:
        icon = "✅" if val else "⬜"
        st.write(f"{icon} {label}")

st.divider()

# =====================================================================
# ЗОЛОТЫЕ ПРАВИЛА ИНВЕСТОРА НА MOEX
# =====================================================================
with st.expander("💡 4 золотых правила разумного инвестора на Мосбирже", expanded=False):
    r1, r2, r3, r4 = st.columns(4)
    with r1:
        with st.container(border=True):
            st.markdown("**🛡️ Долг — враг №1**")
            st.caption("При ключевой ставке выше 15% закредитованные компании отдают прибыль банкам. Покупайте бизнес с отрицательным чистым долгом.")
    with r2:
        with st.container(border=True):
            st.markdown("**⚖️ Без перекосов**")
            st.caption("Ни одна отдельная акция не должна превышать 12% капитала. Ни один сектор не должен занимать >35% портфеля.")
    with r3:
        with st.container(border=True):
            st.markdown("**⏳ Вход лесенкой**")
            st.caption("Никогда не покупайте на всю сумму в один день. Рынок дает лучшие точки входа тем, кто усредняет покупки с интервалом в 2 недели.")
    with r4:
        with st.container(border=True):
            st.markdown("**🌊 Факт важнее шума**")
            st.caption("Проверяйте AI-выжимку: отделяйте пустой шум от реальных фактов (квартальные отчеты, дивидендные рекомендации СД).")

# =====================================================================
# СВЕРНУТАЯ ТЕХНИЧЕСКАЯ ДОКУМЕНТАЦИЯ
# =====================================================================
with st.expander("🛠️ Техническая документация и архитектура репозитория (README.md)", expanded=False):
    readme_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), "README.md")
    if os.path.exists(readme_path):
        with open(readme_path, "r", encoding="utf-8") as f:
            st.markdown(f.read())
    else:
        st.caption("README.md не найден.")
