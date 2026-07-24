import streamlit as st
import pandas as pd
import requests
from moexalgo import Ticker
from datetime import datetime, timedelta
from io import StringIO

# =====================================================================
# 1. СИСТЕМНЫЕ НАСТРОЙКИ И КОНСТАНТЫ
# =====================================================================
st.set_page_config(layout="wide", page_title="MOEX Intelligence Center")
st.title("🎛 Мониторинг рынка: Цены и Глубокий Фундаментал")

# Список контролируемых узлов на Мосбирже
TICKERS = ['SBER', 'LKOH', 'GAZP', 'YDEX']

# Переводчик тикеров для Смарт-лаба (если на сайте старые/другие имена страниц)
SMARTLAB_MAP = {
    'YDEX': 'YNDX',  # Для Яндекса берем его архивную/текущую страницу на смартлабе
    'SBER': 'SBER',
    'LKOH': 'LKOH',
    'GAZP': 'GAZP'
}

# =====================================================================
# 2. СЛУЖБЫ СБОРА ДАННЫХ (БЭКЕНД)
# =====================================================================

# Служба А: Канал связи с Московской Биржей (живые цены)
@st.cache_data(ttl=600)  # Кэш на 10 минут
def fetch_live_prices(ticker_list):
    combined_df = pd.DataFrame()
    end_date = datetime.now().date()
    start_date = end_date - timedelta(days=30)
    
    for t in ticker_list:
        try:
            asset = Ticker(t)
            candles = asset.candles(start=start_date.isoformat(), end=end_date.isoformat(), period='1D')
            df = pd.DataFrame(candles)
            if not df.empty:
                df['begin'] = pd.to_datetime(df['begin'])
                df = df.set_index('begin')
                combined_df[t] = df['close']
        except Exception as e:
            st.error(f"Сбой линии связи с MOEX для {t}: {e}")
    return combined_df.dropna()


# Служба Б: Парсер глубоких годовых отчетов МСФО (Новый подход)
@st.cache_data(ttl=86400)  # Кэш на 24 часа, данные меняются редко
def fetch_ticker_financials(ticker: str):
    """
    Подключается напрямую к выделенному каналу годовой отчетности эмитента.
    Разворачивает матрицу на 90 градусов и очищает текстовый шум.
    """
    # Используем маппинг для безопасного переключения имени страницы
    smartlab_ticker = SMARTLAB_MAP.get(ticker, ticker)
    url = f"https://smart-lab.ru/q/{smartlab_ticker.upper()}/f/y/"
    
    headers = {
        "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36"
    }
    
    try:
        response = requests.get(url, headers=headers, timeout=10)
        tables = pd.read_html(StringIO(response.text))
        
        if not tables:
            return pd.DataFrame()
            
        df = tables[0]
        
        # Фиксируем имя первой колонки с названиями метрик
        df = df.rename(columns={df.columns[0]: 'Metric'})
        
        # Выбрасываем технические столбцы (например, пустые или со знаком '?')
        df = df[[c for c in df.columns if c != '?']]
        
        # Очистка текстового шума (удаляем пробелы внутри чисел и знаки %)
        for col in df.columns:
            if col != 'Metric':
                df[col] = df[col].astype(str).str.replace(r'[\s%]', '', regex=True)
        
        # Транспонирование: переворачиваем таблицу (Метрики становятся колонками, Годы - строками)
        df = df.set_index('Metric').T
        
        # Приведение очищенных текстовых ячеек к физическим числам float
        for col in df.columns:
            df[col] = pd.to_numeric(df[col], errors='coerce')
            
        # Зачищаем индексы лет от случайных пробелов
        df.index = df.index.astype(str).str.strip()
        
        return df
        
    except Exception as e:
        st.error(f"Критический сбой линии связи с отчетами {ticker}: {e}")
        return pd.DataFrame()


# =====================================================================
# 3. ЗАПУСК ДАТЧИКОВ И ПРЕДВАРИТЕЛЬНАЯ ЗАГРУЗКА ЦЕН
# =====================================================================
with st.spinner("Считывание сигналов с биржевых шин..."):
    live_data = fetch_live_prices(TICKERS)


# =====================================================================
# 4. ИНТЕРФЕЙС ПОЛЬЗОВАТЕЛЯ (ФРОНТЕНД)
# =====================================================================
tab_prices, tab_fundamentals = st.tabs(["📈 Живой график цен", "📊 Глубокая аналитика МСФО"])

# --- ЭКРАН 1: Котировки ---
with tab_prices:
    st.header("Телеметрия цен закрытия за 30 дней")
    if not live_data.empty:
        selected_tickers = st.multiselect(
            "Выбери активы для вывода на экран:", 
            options=TICKERS, 
            default=TICKERS
        )
        
        available_tickers = [t for t in selected_tickers if t in live_data.columns]
        
        if available_tickers:
            normalized_data = (live_data[available_tickers] / live_data[available_tickers].iloc[0] - 1) * 100
            st.line_chart(normalized_data)
            st.dataframe(live_data[available_tickers].tail())
        else:
            st.warning("Выбранные тикеры сейчас недоступны в полученных данных MOEX.")
    else:
        st.error("Шина котировок пуста.")


# --- ЭКРАН 2: Глубокий анализ фундаментала (Переписано под новые ссылки) ---
with tab_fundamentals:
    st.header("Диагностика параметров бизнеса по историческим отчетам")
    
    # Селектор активного канала (выбираем одну компанию из списка)
    target_ticker = st.selectbox("Выбери узел для полной проверки параметров:", options=TICKERS)
    
    with st.spinner(f"Загрузка архива отчетов для {target_ticker}..."):
        df_single = fetch_ticker_financials(target_ticker)
        
    if not df_single.empty:
        # Создаем карту колонок в нижнем регистре для безопасного поиска
        columns_map = {col.lower(): col for col in df_single.columns}
        
        # Динамический гибкий поиск точных названий колонок по ключевым словам
        roe_col = next((v for k, v in columns_map.items() if 'roe' in k), None)
        pe_col = next((v for k, v in columns_map.items() if 'p/e' in k or 'p / e' in k), None)
        profit_col = next((v for k, v in columns_map.items() if 'чистая прибыль' in k), None)
        
        # Вывод экспресс-метрик за последний доступный год
        st.subheader("Текущие экспресс-показатели")
        cols_ui = st.columns(3)
        last_year = df_single.index[-1]
        
        with cols_ui[0]:
            if roe_col:
                val = df_single[roe_col].iloc[-1]
                st.metric(label=f"ROE (Рентабельность) {last_year}", value=f"{val}%" if pd.notna(val) else "Н/Д")
        with cols_ui[1]:
            if pe_col:
                val = df_single[pe_col].iloc[-1]
                st.metric(label=f"Мультипликатор P/E {last_year}", value=f"{val}" if pd.notna(val) else "Н/Д")
        with cols_ui[2]:
            if profit_col:
                val = df_single[profit_col].iloc[-1]
                st.metric(label=f"Чистая прибыль {last_year}", value=f"{val} млрд руб" if pd.notna(val) else "Н/Д")
                
        # Графики временных трендов
        st.write("---")
        st.subheader("Динамика устойчивости бизнеса во времени")
        
        # Собираем доступные для графика метрики
        metrics_to_plot = [c for c in [roe_col, pe_col] if c is not None]
        if metrics_to_plot:
            st.line_chart(df_single[metrics_to_plot])
            
        # Полный вывод "Паспорта оборудования"
        st.subheader("Полный массив считанных данных МСФО (Годовые срезы)")
        st.dataframe(df_single, use_container_width=True)
        
    else:
        st.error(f"Не удалось построить таблицу отчетов для {target_ticker}. Канал пуст.")