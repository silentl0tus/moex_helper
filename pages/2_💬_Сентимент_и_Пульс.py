# pyrefly: ignore [missing-import]
import streamlit as st
import pandas as pd
from pathlib import Path
import sys

# Добавляем корень проекта в sys.path чтобы импорты работали
project_root = Path(__file__).parent.parent
if str(project_root) not in sys.path:
    sys.path.append(str(project_root))

from sentiment_scraper import extract_meaningful_messages, extract_pulse_messages, TICKERS_TO_SCAN

st.set_page_config(page_title="Сентимент и Пульс", page_icon="💬", layout="wide")

st.title("💬 Анализ сентимента (Smart-Lab)")
st.markdown("Здесь вы можете просматривать последние осмысленные сообщения и аналитику по компаниям.")

col1, col2 = st.columns([1, 2])

with col1:
    st.subheader("Выбор компании")
    selected_ticker = st.selectbox(
        "Выберите тикер из списка",
        options=TICKERS_TO_SCAN,
        index=0
    )
    custom_ticker = st.text_input("Или введите свой тикер (например, GAZP):").upper()
    
    ticker_to_search = custom_ticker if custom_ticker else selected_ticker
    
    st.markdown("---")
    st.subheader("Источник и Фильтры")
    source_option = st.radio("Источник данных:", ["Smart-Lab (Форум)", "Тинькофф Пульс"])
    filter_option = st.radio(
        "Показать сообщения:",
        options=["Все осмысленные", "Только 🟢 Позитив", "Только 🔴 Негатив", "Только 📊 Аналитика"]
    )
    
    if "force_reload" not in st.session_state:
        st.session_state.force_reload = False
        
    if st.button("🔄 Загрузить свежие данные", type="primary", use_container_width=True):
        st.session_state.force_reload = True
    else:
        st.session_state.force_reload = False

@st.cache_data(ttl=600, show_spinner=False)
def get_messages(ticker, source, force_reload=False):
    if source == "Тинькофф Пульс":
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
        
        c1, c2, c3, c4 = st.columns(4)
        c1.metric("Всего", len(messages))
        c2.metric("🟢 Позитив", pos_count)
        c3.metric("🔴 Негатив", neg_count)
        c4.metric("📊 Аналитика", an_count)
        
        st.markdown(f"Отображено сообщений: **{len(filtered)}**")
        st.divider()
        
        for i, m in enumerate(filtered):
            with st.container(border=True):
                # Шапка карточки
                head_cols = st.columns([3, 1, 1])
                with head_cols[0]:
                    st.markdown(f"**👤 {m['author']}**")
                with head_cols[1]:
                    st.markdown(f"*{m['time']}*")
                with head_cols[2]:
                    # Бейдж
                    if m['trend'] == 'positive': badge = "🟢 Позитив"
                    elif m['trend'] == 'negative': badge = "🔴 Негатив"
                    elif m['trend'] == 'analytics': badge = "📊 Аналитика"
                    else: badge = "⚪ Нейтрально"
                    st.markdown(badge)
                    
                st.markdown(m['text'])
                
                # Подвал карточки
                foot_cols = st.columns([4, 1])
                with foot_cols[0]:
                    st.caption(f"Слова: поз: {m['pos']} | нег: {m['neg']} | ан: {m['analytics']}")
                with foot_cols[1]:
                    st.markdown(f"[🔗 Источник]({m['link']})")
