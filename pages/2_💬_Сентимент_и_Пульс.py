# pyrefly: ignore [missing-import]
import streamlit as st
import pandas as pd
from pathlib import Path
import sys
import importlib

# Добавляем корень проекта в sys.path чтобы импорты работали
project_root = Path(__file__).resolve().parent.parent
if str(project_root) not in sys.path:
    sys.path.insert(0, str(project_root))

import sentiment_scraper
# В Streamlit Cloud при hot-reload модули верхнего уровня кэшируются в sys.modules без новых функций.
# Принудительно перезагружаем sentiment_scraper для гарантированного получения актуальных функций:
try:
    sentiment_scraper = importlib.reload(sentiment_scraper)
except Exception:
    pass

from sentiment_scraper import (
    extract_meaningful_messages,
    extract_pulse_messages,
    extract_aggregated_messages,
    filter_relevant_messages,
    filter_messages_by_date,
    parse_time_to_dt,
    generate_structured_summary,
    summarize_with_openrouter,
    summarize_with_hf,
    DEFAULT_OPENROUTER_MODEL,
    OPENROUTER_FREE_MODELS,
    FALLBACK_TICKERS,
    COMPANY_NAMES,
    TICKER_ALIASES,
    resolve_ticker,
    get_all_supported_tickers,
    POSITIVE_WORDS,
    NEGATIVE_WORDS,
    ANALYTICS_WORDS
)
import re
import os

st.set_page_config(page_title="Сентимент и Пульс | MOEX Helper", page_icon="💬", layout="wide")

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

st.title("💬 Анализ сентимента (Пульс + Smart-Lab)")
st.markdown("Здесь вы можете агрегировать последние осмысленные сообщения и аналитику инвесторов из **Т-Банк Пульс** и **Smart-Lab**.")

col1, col2 = st.columns([1, 2])

with col1:
    st.subheader("Выбор компании")

    available_tickers = get_all_supported_tickers()
    if not available_tickers:
        available_tickers = sorted(FALLBACK_TICKERS)

    # Предзагрузка тикера из query_params или session_state (из Мастера отбора)
    url_ticker = st.query_params.get("ticker", "").upper().strip()
    session_ticker = str(st.session_state.get("selected_sentiment_ticker", "")).upper().strip()
    preset_raw = url_ticker or session_ticker
    preset_ticker = resolve_ticker(preset_raw) if preset_raw else ""

    default_idx = 0
    if preset_ticker and preset_ticker in available_tickers:
        default_idx = available_tickers.index(preset_ticker)
    elif "SBER" in available_tickers:
        default_idx = available_tickers.index("SBER")

    selected_ticker = st.selectbox(
        "Выберите компанию из списка (поиск по тикеру или названию):",
        options=available_tickers,
        index=default_idx,
        format_func=lambda t: f"{t} — {COMPANY_NAMES.get(t, t)}"
    )
    custom_ticker_input = st.text_input("Или введите свой тикер / название (например, CIAN, Циан, SBER):").strip()
    
    if custom_ticker_input:
        resolved = resolve_ticker(custom_ticker_input)
        if resolved != custom_ticker_input.upper():
            st.info(f"💡 Запрос **'{custom_ticker_input}'** сопоставлен с тикером MOEX: **{resolved}** ({COMPANY_NAMES.get(resolved, '')})")
        ticker_to_search = resolved
    else:
        ticker_to_search = selected_ticker
    
    st.markdown("---")
    st.subheader("Источник и Фильтры")
    source_option = st.radio(
        "Источник данных:",
        ["Все источники (Пульс + Smart-Lab)", "Т-Банк Пульс", "Smart-Lab (Форум)"],
        index=0
    )
    filter_option = st.radio(
        "Показать сообщения:",
        options=["Все осмысленные", "Только 🟢 Позитив", "Только 🔴 Негатив", "Только 📊 Аналитика"]
    )
    strict_filter = st.checkbox(
        "🎯 Скрывать спам (только о компании)",
        value=True,
        help="Отсекает общие макро-сводки и посты спам-ботов со списками из 10+ тикеров, в которых нет текста о выбранной компании."
    )
    
    st.markdown("---")
    st.subheader("Период анализа")
    period_option = st.selectbox(
        "Окно анализа сообщений:",
        ["За последний месяц (30 дней)", "За 2 недели (14 дней)", "За 3 месяца (90 дней)", "Все доступные сообщения"],
        index=0,
        help="По умолчанию анализ сентимента строго ограничен последними 30 днями от момента запроса."
    )
    days_map = {
        "За последний месяц (30 дней)": 30,
        "За 2 недели (14 дней)": 14,
        "За 3 месяца (90 дней)": 90,
        "Все доступные сообщения": 3650
    }
    max_age_days = days_map.get(period_option, 30)

    st.markdown("---")
    show_full = st.checkbox("Показывать полные сообщения", value=False)
    
    st.markdown("---")
    st.subheader("🤖 OpenRouter AI (Бесплатно)")
    default_openrouter_key = ""
    openrouter_keys = ["OPENROUTER_API_KEY", "OPENROUTER_KEY", "OPENROUTER_TOKEN"]
    
    # 1. Проверяем Streamlit Secrets
    for k in openrouter_keys:
        try:
            if k in st.secrets and st.secrets[k]:
                default_openrouter_key = str(st.secrets[k]).strip()
                break
        except Exception:
            pass

    # 2. Проверяем переменные окружения и .env
    if not default_openrouter_key:
        try:
            from dotenv import load_dotenv
            load_dotenv()
        except Exception:
            pass
        for k in openrouter_keys:
            val = os.getenv(k)
            if val and val.strip():
                default_openrouter_key = val.strip()
                break

    openrouter_key_input = st.text_input(
        "OpenRouter API Key (sk-or-v1-...):",
        value=default_openrouter_key,
        type="password",
        help="Бесплатный ключ с сайта openrouter.ai/settings/keys. Запросы отправляются только к бесплатным моделям (:free)."
    )

    selected_openrouter_model = st.selectbox(
        "Бесплатная модель OpenRouter:",
        options=OPENROUTER_FREE_MODELS,
        index=0,
        help="Модели с суффиксом ':free' и 'openrouter/free' работают без списания средств ($0.00)."
    )

    if not openrouter_key_input:
        st.caption("💡 *Без ключа работает встроенная 3-колоночная выжимка. С ключом доступна генерация аналитического резюме через бесплатную нейросеть.*")

    if "force_reload" not in st.session_state:
        st.session_state.force_reload = False
        
    if st.button("🔄 Загрузить свежие данные", type="primary", width="stretch"):
        st.session_state.force_reload = True
    else:
        st.session_state.force_reload = False

@st.cache_data(ttl=600, show_spinner=False)
def get_messages(ticker, source, max_age_days=30, force_reload=False):
    if source == "Все источники (Пульс + Smart-Lab)":
        return extract_aggregated_messages(ticker, max_messages=60, max_age_days=max_age_days)
    elif source == "Т-Банк Пульс":
        return extract_pulse_messages(ticker, max_messages=50, max_age_days=max_age_days)
    else:
        return extract_meaningful_messages(ticker, max_pages=2, max_messages=50, max_age_days=max_age_days)

with col2:
    import datetime
    now_dt = datetime.datetime.now()
    start_dt = now_dt - datetime.timedelta(days=max_age_days)
    date_range_str = f"с {start_dt.strftime('%d.%m.%Y')} по {now_dt.strftime('%d.%m.%Y')}"

    comp_name = COMPANY_NAMES.get(ticker_to_search, "")
    comp_suffix = f" — {comp_name}" if comp_name else ""
    st.subheader(f"Лента сообщений: {ticker_to_search}{comp_suffix}")
    st.caption(f"⏱️ Окно анализа сообщений: **{period_option}** ({date_range_str})")
    
    if st.session_state.force_reload:
        get_messages.clear()
        
    with st.spinner("Загрузка данных..."):
        messages = get_messages(ticker_to_search, source_option, max_age_days=max_age_days, force_reload=st.session_state.force_reload)
        if max_age_days:
            messages = filter_messages_by_date(messages, max_age_days=max_age_days)
        
    if not messages:
        if max_age_days <= 31:
            st.info(f"ℹ️ **За последний месяц ({date_range_str}) новых сообщений и обсуждений по компании {ticker_to_search} не найдено.**")
        else:
            st.info(f"ℹ️ **За выбранный период ({date_range_str}) сообщений по компании {ticker_to_search} не найдено.**")

        st.markdown("""
        > **Что это означает для инвестора:**
        > * По эмитенту сейчас **информационный штиль**: нет острых новостных поводов, корпоративных скандалов, судебных исков или срывов дивидендов.
        > * Сентимент инфополя оценивается как **нейтральный (0.0)**.
        > * Для принятия инвестиционного решения используйте фундаментальные мультипликаторы (P/E, P/B, ROE, долг) на странице **Мастер подбора**.
        """)
    else:
        if strict_filter:
            messages = filter_relevant_messages(messages, ticker_to_search)

        # Применяем фильтр
        filtered = []
        for m in messages:
            if filter_option == "Все осмысленные":
                filtered.append(m)
            elif filter_option == "Только 🟢 Позитив" and m["trend"] == "positive":
                filtered.append(m)
            elif filter_option == "Только 🔴 Негатив" and m["trend"] == "negative":
                filtered.append(m)
            elif filter_option == "Только 📊 Аналитика" and (m["trend"] == "analytics" or m["analytics"] > 0):
                filtered.append(m)
                
        # Сводка
        pos_count = sum(1 for m in messages if m["trend"] == "positive")
        neg_count = sum(1 for m in messages if m["trend"] == "negative")
        an_count = sum(1 for m in messages if m["trend"] == "analytics" or m["analytics"] > 0)
        pulse_count = sum(1 for m in messages if m.get("source") == "Пульс")
        smart_count = sum(1 for m in messages if m.get("source") == "Smart-Lab")
        
        c1, c2, c3, c4 = st.columns(4)
        c1.metric(
            "Всего сообщений",
            len(messages),
            f"🟣 Пульс: {pulse_count} │ 🔵 Смарт: {smart_count}" if pulse_count and smart_count else None
        )
        c2.metric("🟢 Позитив", pos_count)
        c3.metric("🔴 Негатив", neg_count)
        c4.metric("📊 Аналитика", an_count)
        
        st.markdown(f"Отображено сообщений: **{len(filtered)}**")
        st.divider()

        if not filtered:
            st.info(f"ℹ️ За выбранный период сообщений с категорией «{filter_option}» не найдено (всего сообщений за период: {len(messages)}).")
        else:
            st.markdown("#### ⚡ Выжимка и ключевые тезисы")
            
            openrouter_active = bool(openrouter_key_input and openrouter_key_input.strip())
            c_sum1, c_sum2 = st.columns([3, 1])
            with c_sum1:
                st.caption(f"Анализирует обсуждения инвесторов строго по эмитенту **{ticker_to_search}** ({date_range_str}).")
            with c_sum2:
                run_ai = st.button("🤖 AI-выжимка (OpenRouter)", help=f"Запустить аналитическое резюме через бесплатную модель {selected_openrouter_model}", disabled=not openrouter_active)

            if run_ai and openrouter_active:
                with st.spinner(f"Запрос к бесплатной нейросети ({selected_openrouter_model})..."):
                    ai_res = summarize_with_openrouter(
                        filtered,
                        ticker=ticker_to_search,
                        api_key=openrouter_key_input,
                        model=selected_openrouter_model
                    )
                    ai_summary_text = ai_res.get("ai_summary")
                    if ai_summary_text:
                        if ai_summary_text.startswith("⚠️") or ai_summary_text.startswith("❌") or ai_summary_text.startswith("⏳"):
                            st.warning(ai_summary_text)
                        else:
                            st.success(f"**🤖 Нейросетевое резюме (`{ai_res.get('model', selected_openrouter_model)}`):**\n\n{ai_summary_text}")
                    struct_data = ai_res.get("structured", {})
            else:
                struct_data = generate_structured_summary(filtered, ticker=ticker_to_search)

            pos_list = struct_data.get("pos", [])
            neg_list = struct_data.get("neg", [])
            an_list = struct_data.get("an", [])

            if pos_list or neg_list or an_list:
                s_col1, s_col2, s_col3 = st.columns(3)
                with s_col1:
                    st.markdown("**🟢 Драйверы роста (Позитив)**")
                    if pos_list:
                        for item in pos_list:
                            st.markdown(f"- {item}")
                    else:
                        st.caption("Явных позитивных тезисов не найдено.")
                with s_col2:
                    st.markdown("**🔴 Риски и сомнения (Негатив)**")
                    if neg_list:
                        for item in neg_list:
                            st.markdown(f"- {item}")
                    else:
                        st.caption("Явных негативных тезисов не найдено.")
                with s_col3:
                    st.markdown("**📊 Факты, отчеты и цифры**")
                    if an_list:
                        for item in an_list:
                            st.markdown(f"- {item}")
                    else:
                        st.caption("Фактических данных не выделено.")
            else:
                st.info("Не удалось составить сводку по текущей выборке сообщений.")
                
            st.divider()
            
            if show_full:
                for i, m in enumerate(filtered):
                    with st.container(border=True):
                        head_cols = st.columns([3, 1, 1])
                        with head_cols[0]:
                            src_badge = "🟣 Пульс" if m.get("source") == "Пульс" else "🔵 Smart-Lab"
                            st.markdown(f"**👤 {m['author']}** &nbsp; `{src_badge}`")
                        with head_cols[1]:
                            st.markdown(f"*{m['time']}*")
                        with head_cols[2]:
                            if m['trend'] == 'positive': badge = "🟢 Позитив"
                            elif m['trend'] == 'negative': badge = "🔴 Негатив"
                            elif m['trend'] == 'analytics': badge = "📊 Аналитика"
                            else: badge = "⚪ Нейтрально"
                            st.markdown(badge)
                            
                        st.markdown(m['text'])
                        
                        foot_cols = st.columns([4, 1])
                        with foot_cols[0]:
                            st.caption(f"Слова: поз: {m['pos']} | нег: {m['neg']} | ан: {m['analytics']}")
                        with foot_cols[1]:
                            st.markdown(f"[🔗 Источник]({m['link']})")
            else:
                st.caption("Полные карточки сообщений скрыты. Включите галочку **'Показывать полные сообщения'** в левом меню, чтобы их увидеть.")
