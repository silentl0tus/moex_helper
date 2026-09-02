# pyrefly: ignore [missing-import]
import streamlit as st
import pandas as pd
from pathlib import Path
import sys

# Добавляем корень проекта в sys.path чтобы импорты работали
project_root = Path(__file__).parent.parent
if str(project_root) not in sys.path:
    sys.path.append(str(project_root))

from sentiment_scraper import extract_meaningful_messages, extract_pulse_messages, TICKERS_TO_SCAN, POSITIVE_WORDS, NEGATIVE_WORDS, ANALYTICS_WORDS
import re

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
    
    st.markdown("---")
    show_full = st.checkbox("Показывать полные сообщения", value=False)
    
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

def generate_summary(messages):
    sentences = []
    for m in messages:
        parts = re.split(r'(?<=[.!?\n])\s+', m["text"])
        for p in parts:
            p = p.strip()
            if len(p) < 30 or len(p) > 200:
                continue
            
            p_lower = p.lower()
            
            has_pos = any(re.search(r'\b' + w + r'[а-я]*\b', p_lower) for w in POSITIVE_WORDS)
            has_neg = any(re.search(r'\b' + w + r'[а-я]*\b', p_lower) for w in NEGATIVE_WORDS)
            has_an = any(re.search(r'\b' + w + r'[а-я]*\b', p_lower) for w in ANALYTICS_WORDS)
            
            if has_pos or has_neg or has_an:
                icon = "🟢" if has_pos else "🔴" if has_neg else "📊"
                sentences.append((icon, p))
                
    unique_sents = []
    seen = set()
    for icon, s in sentences:
        if s not in seen:
            seen.add(s)
            unique_sents.append(f"{icon} {s}")
            
    return unique_sents[:7]

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
        
        summary_sentences = generate_summary(filtered)
        if summary_sentences:
            st.info("**⚡ Ключевые тезисы из обсуждений (Выжимка):**\n\n" + "\n".join([f"- {s}" for s in summary_sentences]))
        else:
            st.info("**⚡ Ключевые тезисы из обсуждений (Выжимка):**\n\nНе удалось составить сводку.")
            
        st.divider()
        
        if show_full:
            for i, m in enumerate(filtered):
                with st.container(border=True):
                    head_cols = st.columns([3, 1, 1])
                    with head_cols[0]:
                        st.markdown(f"**👤 {m['author']}**")
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
