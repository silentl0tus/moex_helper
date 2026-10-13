# pyrefly: ignore [missing-import]
import streamlit as st
import pandas as pd
from pathlib import Path
import sys
import importlib

# Добавляем корень проекта в sys.path чтобы импорты работали
project_root = Path(__file__).parent.parent
if str(project_root) not in sys.path:
    sys.path.append(str(project_root))

import sentiment_scraper
# В Streamlit Cloud при hot-reload старый sentiment_scraper может зависнуть в sys.modules без новых функций
if not hasattr(sentiment_scraper, "generate_structured_summary") or not hasattr(sentiment_scraper, "extract_aggregated_messages"):
    sentiment_scraper = importlib.reload(sentiment_scraper)

from sentiment_scraper import (
    extract_meaningful_messages,
    extract_pulse_messages,
    extract_aggregated_messages,
    generate_structured_summary,
    summarize_with_hf,
    FALLBACK_TICKERS,
    POSITIVE_WORDS,
    NEGATIVE_WORDS,
    ANALYTICS_WORDS
)
import re
import os

st.set_page_config(page_title="Сентимент и Пульс", page_icon="💬", layout="wide")

st.title("💬 Анализ сентимента (Пульс + Smart-Lab)")
st.markdown("Здесь вы можете агрегировать последние осмысленные сообщения и аналитику инвесторов из **Т-Банк Пульс** и **Smart-Lab**.")

col1, col2 = st.columns([1, 2])

with col1:
    st.subheader("Выбор компании")
    selected_ticker = st.selectbox(
        "Выберите тикер из списка",
        options=FALLBACK_TICKERS,
        index=0
    )
    custom_ticker = st.text_input("Или введите свой тикер (например, GAZP):").upper()
    
    ticker_to_search = custom_ticker if custom_ticker else selected_ticker
    
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
    
    st.markdown("---")
    show_full = st.checkbox("Показывать полные сообщения", value=False)
    
    st.markdown("---")
    st.subheader("🤖 Hugging Face AI")
    default_hf_token = ""
    try:
        default_hf_token = st.secrets.get("HF_TOKEN", "")
    except Exception:
        pass
    if not default_hf_token:
        default_hf_token = os.getenv("HF_TOKEN", "")

    hf_token_input = st.text_input(
        "HF Access Token (Read):",
        value=default_hf_token,
        type="password",
        help="Бесплатный токен 'Read' с сайта huggingface.co/settings/tokens. Позволяет вызывать нейросеть-суммаризатор через API без нагрузки на память Streamlit."
    )
    if not hf_token_input:
        st.caption("💡 *Без токена работает встроенная выжимка. С токеном доступна AI-генерация через нейросеть.*")

    if "force_reload" not in st.session_state:
        st.session_state.force_reload = False
        
    if st.button("🔄 Загрузить свежие данные", type="primary", width="stretch"):
        st.session_state.force_reload = True
    else:
        st.session_state.force_reload = False

@st.cache_data(ttl=600, show_spinner=False)
def get_messages(ticker, source, force_reload=False):
    if source == "Все источники (Пульс + Smart-Lab)":
        return extract_aggregated_messages(ticker, max_messages=60)
    elif source == "Т-Банк Пульс":
        return extract_pulse_messages(ticker, max_messages=50)
    else:
        return extract_meaningful_messages(ticker, max_pages=2, max_messages=50)

with col2:
    st.subheader(f"Лента сообщений: {ticker_to_search}")
    
    if st.session_state.force_reload:
        get_messages.clear()
        
    with st.spinner("Загрузка данных..."):
        messages = get_messages(ticker_to_search, source_option, st.session_state.force_reload)
        
    if not messages:
        st.warning(f"Не удалось найти осмысленных сообщений для тикера {ticker_to_search}.")
    else:
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
        
        st.markdown("#### ⚡ Выжимка и ключевые тезисы")
        
        hf_active = bool(hf_token_input and hf_token_input.strip())
        c_sum1, c_sum2 = st.columns([3, 1])
        with c_sum1:
            st.caption("Анализирует обсуждения сообщества инвесторов из Т-Банк Пульс и Smart-Lab.")
        with c_sum2:
            run_ai = st.button("🤖 AI-выжимка (HF)", help="Запустить нейросетевую суммаризацию через Hugging Face Serverless API", disabled=not hf_active)

        if run_ai and hf_active:
            with st.spinner("Запрос к нейросети Hugging Face (IlyaGusev/rut5_base_sum_gazeta)..."):
                hf_res = summarize_with_hf(filtered, ticker_to_search, hf_token=hf_token_input)
                if hf_res.get("ai_summary"):
                    st.success(f"**🤖 Нейросетевое резюме (`{hf_res.get('model', 'Hugging Face')}`):**\n\n{hf_res['ai_summary']}")
                struct_data = hf_res.get("structured", {})
        else:
            struct_data = generate_structured_summary(filtered)

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
