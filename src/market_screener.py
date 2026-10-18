"""
Модуль «Вид рынка / Плиточный скринер» (Market Screener & Heat Map).

Отображает интерактивную тепловую карту рынка акций MOEX (TQBR) и сырьевой барометр
с динамикой котировок за ключевые инвестиционные периоды:
- День (1D)
- Неделя (1W)
- Месяц (1M)
- Квартал (3M / 1Q)
- С начала года (YTD)
"""

import datetime
from concurrent.futures import ThreadPoolExecutor
from typing import Dict, List, Optional, Tuple

import pandas as pd
import requests
import streamlit as st

# =====================================================================
# СПРАВОЧНИКИ: КОРОТКИЕ ИМЕНА И СЕКТОРЫ
# =====================================================================

TICKER_SHORT_NAMES = {
    "PLZL": "Полюс",
    "HYDR": "РусГидро",
    "OZON": "OZON",
    "MRKP": "МРСК ЦП",
    "FESH": "ДВМП",
    "RTKM": "Ростелеком",
    "RTKMP": "Ростелеком-п",
    "CHMF": "Северсталь",
    "BELU": "НоваБев",
    "KAZT": "Куйбышевазот",
    "KAZTP": "Куйбышевазот-п",
    "AFKS": "Система",
    "PHOR": "ФосАгро",
    "ALRS": "АЛРОСА",
    "DIAS": "Диасофт",
    "AFLT": "Аэрофлот",
    "RASP": "Распадская",
    "LSNG": "Ленэнерго",
    "LSNGP": "Ленэнерго-п",
    "UPRO": "Юнипро",
    "NVTK": "НОВАТЭК",
    "LSRG": "ЛСР",
    "X5": "Х5",
    "FIVE": "Х5",
    "GAZP": "Газпром",
    "MGNT": "Магнит",
    "MSRS": "МОЭСК",
    "MDMG": "Мать и дитя",
    "RAGR": "Русагро",
    "IRAO": "ИнтерРАО",
    "WUSH": "ВУШ",
    "YDEX": "Яндекс",
    "YNDX": "Яндекс",
    "MTLR": "Мечел",
    "MTLRP": "Мечел-п",
    "ETLN": "Эталон",
    "NKNC": "НКНХ",
    "NKNCP": "НКНХ-п",
    "MTSS": "МТС",
    "SPBE": "СПБ Биржа",
    "ENPG": "Эн+",
    "SNGS": "Сургфгз",
    "SNGSP": "Сургфгз-п",
    "SVCB": "Совкомбанк",
    "MAGN": "ММК",
    "DOMRF": "ДомРФ",
    "RENI": "РенСтрах",
    "OZPH": "Озон Фарма",
    "NLMK": "НЛМК",
    "POSI": "Позитив",
    "RUAL": "РУСАЛ",
    "RNFT": "Русснефть",
    "T": "Тбанк",
    "TCSG": "Тбанк",
    "MBNK": "МТС Банк",
    "FLOT": "Совкомфлот",
    "BSPB": "БСП",
    "UGLD": "ЮГК",
    "UGC": "ЮГК",
    "TRNFP": "Транснефть",
    "SBER": "Сбер",
    "SBERP": "Сбер-п",
    "MOEX": "Мосбиржа",
    "GMKN": "Норникель",
    "GCHE": "Черкизово",
    "VTBR": "ВТБ",
    "ROSN": "Роснефть",
    "NMTP": "НМТП",
    "HEAD": "Хэдхантер",
    "SIBN": "Газпромнефть",
    "TATN": "Татнефть",
    "TATNP": "Татнефть-п",
    "LKOH": "ЛУКОЙЛ",
    "AQUA": "Инарктика",
    "PRMD": "Промомед",
    "ASTR": "Астра",
    "DATA": "Аренадата",
    "SOFL": "Софтлайн",
    "VKCO": "VK",
    "TRMK": "ТМК",
    "SELG": "Селигдар",
    "SFIN": "ЭсЭфАй",
    "SGZH": "Сегежа",
    "PIKK": "ПИК",
    "SMLT": "Самолёт",
    "EUTR": "ЕвроТранс",
    "CNRU": "Циан",
    "CIAN": "Циан",
    "CBOM": "МКБ",
    "FEES": "Россети",
    "IVAT": "ИВА",
    "BANE": "Башнефть",
    "BANEP": "Башнефть-п",
    "MSNG": "Мосэнерго"
}

SECTOR_MAP = {
    # Банки & Финансы
    "SBER": "Банки", "SBERP": "Банки", "VTBR": "Банки", "T": "Банки", "TCSG": "Банки",
    "BSPB": "Банки", "CBOM": "Банки", "SVCB": "Банки", "MBNK": "Банки", "MOEX": "Финансы",
    "SPBE": "Финансы", "DOMRF": "Финансы", "RENI": "Страхование", "SFIN": "Финансы",
    # Нефть & Газ
    "LKOH": "Нефть и газ", "ROSN": "Нефть и газ", "GAZP": "Нефть и газ", "NVTK": "Нефть и газ",
    "TATN": "Нефть и газ", "TATNP": "Нефть и газ", "SIBN": "Нефть и газ", "SNGS": "Нефть и газ",
    "SNGSP": "Нефть и газ", "TRNFP": "Транспорт нефти", "BANE": "Нефть и газ", "BANEP": "Нефть и газ",
    "RNFT": "Нефть и газ",
    # Металлы & Добыча
    "GMKN": "Металлургия", "CHMF": "Металлургия", "NLMK": "Металлургия", "MAGN": "Металлургия",
    "PLZL": "Золотодобыча", "ALRS": "Алмазы", "RUAL": "Металлургия", "SELG": "Золотодобыча",
    "UGLD": "Золотодобыча", "UGC": "Золотодобыча", "MTLR": "Уголь и сталь", "MTLRP": "Уголь и сталь",
    "RASP": "Уголь", "TRMK": "Металлургия",
    # IT & Интернет
    "YDEX": "IT и Интернет", "YNDX": "IT и Интернет", "OZON": "E-Commerce", "VKCO": "IT и Интернет",
    "POSI": "Кибербезопасность", "ASTR": "IT (ПО)", "DIAS": "IT (Финтех ПО)", "DATA": "IT (СУБД)",
    "SOFL": "IT (Интеграция)", "HEAD": "Рекрутинг и HR", "IVAT": "IT (Связь)",
    # Потребительский сектор & Ритейл
    "MGNT": "Ритейл", "X5": "Ритейл", "FIVE": "Ритейл", "BELU": "Потребительский",
    "AQUA": "Аквакультура", "MDMG": "Медицина", "GCHE": "Агропром", "OZPH": "Фармацевтика",
    "PRMD": "Фармацевтика", "WUSH": "Шеринг",
    # Энергетика & Сети
    "IRAO": "Энергетика", "HYDR": "Гидроэнергетика", "UPRO": "Энергетика", "MSNG": "Энергетика",
    "FEES": "Электросети", "LSNG": "Электросети", "LSNGP": "Электросети", "MRKP": "Электросети",
    "MSRS": "Электросети", "ENPG": "Энергетика / Алюминий",
    # Химия & Удобрения
    "PHOR": "Удобрения", "KAZT": "Химия", "KAZTP": "Химия", "NKNC": "Нефтехимия", "NKNCP": "Нефтехимия",
    # Транспорт & Логистика
    "AFLT": "Авиация", "FLOT": "Танкерный флот", "FESH": "Порты и логистика", "NMTP": "Порты",
    # Девелопмент & Недвижимость
    "PIKK": "Девелопмент", "SMLT": "Девелопмент", "ETLN": "Девелопмент", "LSRG": "Девелопмент",
    "CNRU": "Недвижимость онлайн", "CIAN": "Недвижимость онлайн",
    # Холдинги & Прочее
    "AFKS": "Холдинги", "SGZH": "Лесопромышленность", "EUTR": "Топливный ритейл"
}

# Список 65 ключевых тикеров MOEX TQBR для плиточного вида рынка
SCREENER_TICKERS = [
    "PLZL", "HYDR", "OZON", "MRKP", "FESH", "RTKM", "CHMF", "BELU",
    "KAZT", "AFKS", "PHOR", "ALRS", "DIAS", "AFLT", "RASP", "LSNGP",
    "UPRO", "NVTK", "LSRG", "X5", "GAZP", "MGNT", "MSRS", "MDMG",
    "RAGR", "IRAO", "WUSH", "YDEX", "MTLR", "ETLN", "NKNC", "MTSS",
    "SPBE", "ENPG", "SNGS", "SVCB", "MAGN", "DOMRF", "RENI", "OZPH",
    "NLMK", "POSI", "RUAL", "RNFT", "T", "MBNK", "FLOT", "BSPB",
    "UGLD", "TRNFP", "SBER", "MOEX", "GMKN", "GCHE", "VTBR", "ROSN",
    "NMTP", "HEAD", "SIBN", "SNGSP", "TATN", "LKOH", "AQUA", "PRMD",
    "ASTR", "DATA", "SOFL", "VKCO", "TRMK", "SELG", "SFIN", "CBOM"
]

# =====================================================================
# СЫРЬЕВОЙ БАРОМЕТР (COMMODITIES & MACRO)
# =====================================================================

COMMODITIES_BASE = [
    # Ряд 1 (8 колонок)
    {"name": "Масло Индия", "ticker": "OIL_IND", "price": 1632.0, "unit": "$/т", "change": 3.6},
    {"name": "Масло РФ", "ticker": "OIL_RU", "price": 1301.0, "unit": "$/т", "change": 0.0},
    {"name": "kUrals", "ticker": "URALS", "price": 106.0, "unit": "", "change": 0.0},
    {"name": "Алюминий", "ticker": "ALI=F", "price": 3098.0, "unit": "", "change": 0.0},
    {"name": "Нефть WTI", "ticker": "CL=F", "price": 99.0, "unit": "", "change": 0.0},
    {"name": "DAP", "ticker": "DAP", "price": 803.0, "unit": "", "change": 0.0},
    {"name": "Диз. маржа ЕС", "ticker": "DIESEL", "price": 71.7, "unit": "", "change": 0.0},
    {"name": "Золото", "ticker": "GC=F", "price": 4181.0, "unit": "", "change": 0.0},
    # Ряд 2 (8 колонок)
    {"name": "Медь", "ticker": "HG=F", "price": 6.57, "unit": "", "change": 0.0},
    {"name": "Газ Азия", "ticker": "GAS_ASIA", "price": 1057.0, "unit": "", "change": 0.0},
    {"name": "LNG Brent", "ticker": "LNG", "price": 508.0, "unit": "", "change": 0.0},
    {"name": "Уголь Австрал.", "ticker": "COAL", "price": 155.0, "unit": "", "change": 0.0},
    {"name": "Газ США", "ticker": "NG=F", "price": 110.0, "unit": "", "change": 0.0},
    {"name": "Палладий", "ticker": "PA=F", "price": 1119.0, "unit": "", "change": 0.0},
    {"name": "Платина", "ticker": "PL=F", "price": 1633.0, "unit": "", "change": 0.0},
    {"name": "Сахар", "ticker": "SB=F", "price": 20.9, "unit": "", "change": 0.0},
    # Ряд 3 (6 колонок)
    {"name": "Серебро", "ticker": "SI=F", "price": 57.3, "unit": "", "change": 0.0},
    {"name": "Жел. руда", "ticker": "IRON", "price": 90.9, "unit": "", "change": 0.0},
    {"name": "Газ ЕС", "ticker": "TTF", "price": 1018.0, "unit": "", "change": 0.0},
    {"name": "Карбамид США", "ticker": "UREA", "price": 482.0, "unit": "", "change": 0.0},
    {"name": "Нефть Brent", "ticker": "BZ=F", "price": 110.0, "unit": "", "change": 0.0},
    {"name": "Пшеница", "ticker": "ZW=F", "price": 661.0, "unit": "", "change": 0.0}
]

@st.cache_data(ttl=600)
def fetch_commodities_barometer() -> List[dict]:
    """Возвращает актуальный срез котировок ключевого сырья с расчётом изменений."""
    items = []
    import yfinance as yf
    
    yf_map = {
        "BZ=F": "Нефть Brent",
        "CL=F": "Нефть WTI",
        "GC=F": "Золото",
        "SI=F": "Серебро",
        "PL=F": "Платина",
        "PA=F": "Палладий",
        "HG=F": "Медь",
        "NG=F": "Газ США",
        "ZW=F": "Пшеница",
        "SB=F": "Сахар"
    }
    
    live_data = {}
    try:
        yf_tickers = list(yf_map.keys())
        hist = yf.download(yf_tickers, period="5d", interval="1d", progress=False, group_by="ticker")
        for sym in yf_tickers:
            try:
                sub = hist[sym] if sym in hist else None
                if sub is not None and not sub.empty and "Close" in sub:
                    c_clean = sub["Close"].dropna()
                    if len(c_clean) >= 2:
                        p_curr = float(c_clean.iloc[-1])
                        p_prev = float(c_clean.iloc[-2])
                        ch = (p_curr - p_prev) / p_prev * 100.0
                        live_data[sym] = (p_curr, round(ch, 1))
            except Exception:
                pass
    except Exception:
        pass
        
    for base in COMMODITIES_BASE:
        sym = base["ticker"]
        item = dict(base)
        if sym in live_data:
            item["price"] = live_data[sym][0]
            item["change"] = live_data[sym][1]
        items.append(item)
    return items


# =====================================================================
# СБОР ДАННЫХ ПО АКЦИЯМ (1D, 1W, 1M, 3M, YTD)
# =====================================================================

def _fetch_single_ticker_candles(ticker: str, start_date: str) -> Optional[dict]:
    """Запрашивает дневные свечи с начала года для одного тикера и рассчитывает доходность за периоды."""
    url = f"https://iss.moex.com/iss/engines/stock/markets/shares/boards/TQBR/securities/{ticker}/candles.json"
    today = datetime.datetime.now().date()
    d1_cutoff = (today - datetime.timedelta(days=1)).strftime("%Y-%m-%d")
    w1_cutoff = (today - datetime.timedelta(days=7)).strftime("%Y-%m-%d")
    m1_cutoff = (today - datetime.timedelta(days=30)).strftime("%Y-%m-%d")
    q1_cutoff = (today - datetime.timedelta(days=90)).strftime("%Y-%m-%d")
    
    try:
        r = requests.get(url, params={"interval": 24, "from": start_date, "iss.meta": "off"}, timeout=6)
        if r.status_code != 200:
            return None
        data_json = r.json()
        cols = data_json["candles"]["columns"]
        candles = data_json["candles"]["data"]
        if not candles:
            return None
            
        c_idx = cols.index("close")
        d_idx = cols.index("begin")
        v_idx = cols.index("value") if "value" in cols else None
        
        curr = float(candles[-1][c_idx])
        
        # 1D (День)
        p_1d = float(candles[-2][c_idx]) if len(candles) >= 2 else curr
        ch_1d = ((curr - p_1d) / p_1d * 100.0) if p_1d > 0 else 0.0
        
        # 1W (Неделя / 7 календарных дней назад)
        w_candles = [float(row[c_idx]) for row in candles if row[d_idx][:10] <= w1_cutoff]
        p_1w = w_candles[-1] if w_candles else float(candles[0][c_idx])
        ch_1w = ((curr - p_1w) / p_1w * 100.0) if p_1w > 0 else 0.0
        
        # 1M (Месяц / 30 дней)
        m_candles = [float(row[c_idx]) for row in candles if row[d_idx][:10] <= m1_cutoff]
        p_1m = m_candles[-1] if m_candles else float(candles[0][c_idx])
        ch_1m = ((curr - p_1m) / p_1m * 100.0) if p_1m > 0 else 0.0
        
        # 3M (Квартал / 90 дней)
        q_candles = [float(row[c_idx]) for row in candles if row[d_idx][:10] <= q1_cutoff]
        p_3m = q_candles[-1] if q_candles else float(candles[0][c_idx])
        ch_3m = ((curr - p_3m) / p_3m * 100.0) if p_3m > 0 else 0.0
        
        # YTD (С начала года / первая доступная сессия года)
        p_ytd = float(candles[0][c_idx])
        ch_ytd = ((curr - p_ytd) / p_ytd * 100.0) if p_ytd > 0 else 0.0
        
        vol_rub = float(candles[-1][v_idx]) if v_idx is not None else 0.0
        
        short_name = TICKER_SHORT_NAMES.get(ticker, ticker)
        sector = SECTOR_MAP.get(ticker, "Широкий рынок")
        
        return {
            "ticker": ticker,
            "name": short_name,
            "sector": sector,
            "price": curr,
            "1D": round(ch_1d, 1),
            "1W": round(ch_1w, 1),
            "1M": round(ch_1m, 1),
            "3M": round(ch_3m, 1),
            "YTD": round(ch_ytd, 1),
            "val_mln": round(vol_rub / 1_000_000.0, 1)
        }
    except Exception:
        return None


@st.cache_data(ttl=600)
def fetch_market_screener_data(custom_tickers: Optional[List[str]] = None) -> pd.DataFrame:
    """Параллельно собирает цены и изменения за 1D, 1W, 1M, 3M, YTD для всех акций."""
    target_tickers = custom_tickers or SCREENER_TICKERS
    start_year = f"{datetime.datetime.now().year}-01-01"
    
    # 1. Загрузка котировок из MOEX ISS реального времени для более точного оборота
    rt_url = "https://iss.moex.com/iss/engines/stock/markets/shares/boards/TQBR/securities.json"
    rt_map = {}
    try:
        r = requests.get(rt_url, params={"iss.meta": "off", "iss.only": "securities,marketdata"}, timeout=8)
        if r.status_code == 200:
            js = r.json()
            md_cols = js["marketdata"]["columns"]
            md_data = js["marketdata"]["data"]
            t_idx = md_cols.index("SECID")
            val_idx = md_cols.index("VALTODAY")
            last_idx = md_cols.index("LAST")
            for row in md_data:
                sec = row[t_idx]
                rt_map[sec] = {
                    "val_today": float(row[val_idx] or 0.0),
                    "last": float(row[last_idx]) if row[last_idx] is not None else None
                }
    except Exception:
        pass

    # 2. Параллельный сбор истории свечей
    with ThreadPoolExecutor(max_workers=20) as executor:
        results = [res for res in executor.map(lambda t: _fetch_single_ticker_candles(t, start_year), target_tickers) if res]

    if not results:
        return pd.DataFrame()

    df = pd.DataFrame(results)
    
    # Обогащаем данными реального времени из rt_map если есть
    for idx, row in df.iterrows():
        t = row["ticker"]
        if t in rt_map:
            rt_val = rt_map[t]["val_today"]
            if rt_val > 0:
                df.at[idx, "val_mln"] = round(rt_val / 1_000_000.0, 1)
            if rt_map[t]["last"] is not None and rt_map[t]["last"] > 0:
                df.at[idx, "price"] = rt_map[t]["last"]

    return df


# =====================================================================
# РЕНДЕРИНГ ПЛИТОЧНОЙ ТЕПЛОВОЙ КАРТЫ (HEAT MAP)
# =====================================================================

def _format_price_ru(val: float) -> str:
    """Форматирует цену в удобный для чтения вид (как на биржевом терминале)."""
    if val is None or pd.isna(val):
        return "—"
    if val >= 1000:
        return f"{val:,.0f}".replace(",", " ")
    elif val >= 10:
        return f"{val:.1f}".replace(".", ",")
    elif val >= 1:
        return f"{val:.2f}".replace(".", ",")
    else:
        return f"{val:.4f}".replace(".", ",")


def _get_tile_css_class(ret: float) -> Tuple[str, str]:
    """Возвращает CSS-класс фона и цвет бейджа в зависимости от доходности."""
    if ret is None or pd.isna(ret):
        return "tile-neutral", "#94A3B8"
    if ret >= 10.0:
        return "tile-green-max", "#4ADE80"
    elif ret >= 5.0:
        return "tile-green-high", "#86EFAC"
    elif ret >= 2.0:
        return "tile-green-med", "#86EFAC"
    elif ret >= 0.5:
        return "tile-green-low", "#BBF7D0"
    elif ret >= 0.0:
        return "tile-green-flat", "#CBD5E1"
    elif ret >= -0.5:
        return "tile-red-flat", "#FCA5A5"
    elif ret >= -1.5:
        return "tile-red-low", "#F87171"
    elif ret >= -3.0:
        return "tile-red-med", "#EF4444"
    else:
        return "tile-red-max", "#FCA5A5"


def render_market_view_component(
    screener_df: pd.DataFrame,
    commodities: List[dict],
    my_portfolio_tickers: Optional[List[str]] = None
):
    """
    Основной компонент вида рынка:
    - Сырьевой барометр (Commodities ribbon)
    - Панель управления (Выбор периода: 1D, 1W, 1M, 3M, YTD; секторный фильтр; поиск)
    - Плиточная сетка акций (Heat Map в стиле скриншота терминала)
    - Переключение на детальную таблицу скринера
    """
    # CSS стили интерфейса тепловой карты и сырьевого барометра (защита глаз от яркого белого фона)
    screener_css = """<style>
/* Темный экран терминала для защиты глаз от яркого белого света */
.market-dark-canvas {
    background: #080D1A;
    border: 1px solid #1E293B;
    border-radius: 14px;
    padding: 22px 24px;
    margin-top: 12px;
    margin-bottom: 24px;
    box-shadow: 0 12px 36px rgba(0, 0, 0, 0.45);
}

.market-section-title {
    font-size: 1.45rem;
    font-weight: 800;
    letter-spacing: 0.5px;
    color: #F8FAFC;
    margin-top: 4px;
    margin-bottom: 4px;
    display: flex;
    align-items: center;
    gap: 8px;
}
.market-section-sub {
    font-size: 0.88rem;
    color: #94A3B8;
    margin-bottom: 16px;
}

/* Сетка сырьевых индикаторов */
.commodities-grid {
    display: grid;
    grid-template-columns: repeat(auto-fill, minmax(170px, 1fr));
    gap: 8px;
    margin-bottom: 8px;
}

.comm-card {
    background: #10172A;
    border: 1px solid rgba(255, 255, 255, 0.08);
    border-radius: 8px;
    padding: 10px 12px;
    display: flex;
    flex-direction: column;
    justify-content: space-between;
    min-height: 66px;
    box-sizing: border-box;
    transition: transform 0.15s ease, border-color 0.15s ease;
}
.comm-card:hover {
    transform: translateY(-2px);
    border-color: rgba(255, 255, 255, 0.2);
}
.comm-header {
    display: flex;
    justify-content: space-between;
    align-items: center;
    font-size: 0.90rem;
    color: #94A3B8;
    font-weight: 600;
    line-height: 1.1;
    white-space: nowrap;
    overflow: hidden;
    text-overflow: ellipsis;
}
.comm-val {
    font-size: 1.18rem;
    font-weight: 800;
    color: #F8FAFC;
    margin-top: 4px;
    line-height: 1.2;
}
.comm-unit {
    font-size: 0.78rem;
    color: #64748B;
    font-weight: normal;
    margin-left: 4px;
}

/* КРУПНАЯ СЕТКА ПЛИТОК АКЦИЙ (ПО УМОЛЧАНИЮ) */
.market-tiles-grid.size-large {
    display: grid;
    grid-template-columns: repeat(auto-fill, minmax(215px, 1fr));
    gap: 9px;
    margin-top: 12px;
    margin-bottom: 8px;
}

.m-card-large {
    border-radius: 9px;
    padding: 12px 14px;
    display: flex;
    flex-direction: column;
    justify-content: space-between;
    min-height: 86px;
    box-sizing: border-box;
    transition: transform 0.15s ease, box-shadow 0.15s ease, filter 0.15s ease;
    cursor: default;
    user-select: none;
}
.m-card-large:hover {
    transform: translateY(-2px);
    box-shadow: 0 8px 24px rgba(0,0,0,0.7);
    filter: brightness(1.15);
    z-index: 2;
}
.m-card-large .m-top {
    display: flex;
    justify-content: space-between;
    align-items: center;
    gap: 6px;
}
.m-card-large .m-name {
    font-size: 1.15rem;
    font-weight: 700;
    color: #F8FAFC;
    white-space: nowrap;
    overflow: hidden;
    text-overflow: ellipsis;
    line-height: 1.2;
}
.m-card-large .m-badge {
    font-size: 1.20rem;
    font-weight: 800;
    white-space: nowrap;
    line-height: 1.2;
}
.m-card-large .m-bottom {
    display: flex;
    justify-content: space-between;
    align-items: baseline;
    margin-top: 10px;
}
.m-card-large .m-price {
    font-size: 1.30rem;
    font-weight: 800;
    color: #FFFFFF;
    letter-spacing: -0.2px;
    line-height: 1.2;
}
.m-card-large .m-ticker {
    font-size: 0.85rem;
    color: #94A3B8;
    font-weight: 600;
}

/* КОМПАКТНАЯ СЕТКА ПЛИТОК АКЦИЙ */
.market-tiles-grid.size-compact {
    display: grid;
    grid-template-columns: repeat(auto-fill, minmax(150px, 1fr));
    gap: 6px;
    margin-top: 10px;
    margin-bottom: 8px;
}
.m-card-compact {
    border-radius: 7px;
    padding: 8px 10px;
    display: flex;
    flex-direction: column;
    justify-content: space-between;
    min-height: 60px;
    box-sizing: border-box;
    transition: transform 0.15s ease, filter 0.15s ease;
    cursor: default;
    user-select: none;
}
.m-card-compact:hover {
    transform: translateY(-2px);
    filter: brightness(1.15);
}
.m-card-compact .m-top {
    display: flex;
    justify-content: space-between;
    align-items: center;
    gap: 4px;
}
.m-card-compact .m-name {
    font-size: 0.88rem;
    font-weight: 700;
    color: #F8FAFC;
    white-space: nowrap;
    overflow: hidden;
    text-overflow: ellipsis;
}
.m-card-compact .m-badge {
    font-size: 0.90rem;
    font-weight: 800;
    white-space: nowrap;
}
.m-card-compact .m-bottom {
    display: flex;
    justify-content: space-between;
    align-items: baseline;
    margin-top: 6px;
}
.m-card-compact .m-price {
    font-size: 1.02rem;
    font-weight: 700;
    color: #FFFFFF;
}
.m-card-compact .m-ticker {
    font-size: 0.72rem;
    color: #94A3B8;
}

/* Цвета градиентов доходности плиток (глубокие, мягкие тона) */
.tile-green-max { background: #0E4426; border: 1px solid #10B981; }
.tile-green-high { background: #134E2C; border: 1px solid #16A34A; }
.tile-green-med { background: #154628; border: 1px solid #22C55E; }
.tile-green-low { background: #183D25; border: 1px solid #15803D; }
.tile-green-flat { background: #183324; border: 1px solid #1B4332; }
.tile-neutral { background: #1E293B; border: 1px solid #334155; }
.tile-red-flat { background: #381A1F; border: 1px solid #5C1D26; }
.tile-red-low { background: #541922; border: 1px solid #7F1D2B; }
.tile-red-med { background: #731725; border: 1px solid #991B2D; }
.tile-red-max { background: #8B1224; border: 1px solid #DC2626; }

.portfolio-star {
    color: #F59E0B;
    font-size: 0.85rem;
    margin-right: 3px;
}
</style>"""
    st.markdown(screener_css, unsafe_allow_html=True)

    # 1. СЫРЬЕВОЙ БАРОМЕТР (COMMODITIES)
    if commodities:
        comm_parts = [
            '<div class="market-dark-canvas">'
            '<div class="market-section-title">🛢️ СЫРЬЕВОЙ БАРОМЕТР & МАКРО-ИНДИКАТОРЫ</div>'
            '<div class="market-section-sub">Ключевые бенчмарки нефти, металлов, газа и агропродукции</div>'
            '<div class="commodities-grid">'
        ]
        for c in commodities:
            ch = c.get("change", 0.0)
            if ch > 0:
                ch_str = f'<span style="color:#4ADE80; font-weight:800;">+{ch:.1f}%</span>'
            elif ch < 0:
                ch_str = f'<span style="color:#F87171; font-weight:800;">{ch:.1f}%</span>'
            else:
                ch_str = '<span style="color:#94A3B8;">0%</span>'
            
            p_val = _format_price_ru(c.get("price"))
            unit = c.get("unit", "")
            unit_span = f'<span class="comm-unit">{unit}</span>' if unit else ''
            
            comm_parts.append(
                f'<div class="comm-card">'
                f'<div class="comm-header"><span>{c["name"]}</span>{ch_str}</div>'
                f'<div class="comm-val">{p_val}{unit_span}</div>'
                f'</div>'
            )
        comm_parts.append('</div></div>')
        st.markdown("".join(comm_parts), unsafe_allow_html=True)

    # 2. ПАНЕЛЬ ВЫБОРА ПЕРИОДА, РАЗМЕРА И ФИЛЬТРОВ
    col_per, col_view, col_size, col_sec, col_search = st.columns([2.0, 1.0, 1.2, 1.4, 1.4])
    
    with col_per:
        period = st.radio(
            "Инвестиционный период:",
            ["Неделя (1W)", "День (1D)", "Месяц (1M)", "Квартал (3M)", "С начала года (YTD)"],
            horizontal=True,
            index=0
        )
        
    period_key_map = {
        "День (1D)": "1D",
        "Неделя (1W)": "1W",
        "Месяц (1M)": "1M",
        "Квартал (3M)": "3M",
        "С начала года (YTD)": "YTD"
    }
    p_key = period_key_map.get(period, "1W")

    with col_view:
        view_mode = st.radio("Режим:", ["🟩 Плитки", "📋 Таблица"], horizontal=True)

    with col_size:
        tile_size = st.radio("Размер:", ["🔍 Крупные", "📱 Компактные"], horizontal=True, index=0)

    with col_sec:
        all_sectors = ["Все сектора"] + sorted(list(set(screener_df["sector"].dropna().unique())))
        selected_sector = st.selectbox("Сектор:", all_sectors)

    with col_search:
        search_query = st.text_input("🔍 Поиск по тикеру/имени:", placeholder="Сбер, OZON...").strip().upper()

    # Фильтрация данных
    df_filtered = screener_df.copy()
    
    if selected_sector != "Все сектора":
        df_filtered = df_filtered[df_filtered["sector"] == selected_sector]
        
    if search_query:
        df_filtered = df_filtered[
            df_filtered["ticker"].str.contains(search_query, na=False) |
            df_filtered["name"].str.upper().str.contains(search_query, na=False)
        ]
        
    # Сортировка по выбранному периоду (от лидеров роста к падению, как на скриншоте)
    df_filtered = df_filtered.sort_values(by=p_key, ascending=False).reset_index(drop=True)
    
    # Метрики динамики
    n_up = sum(1 for v in df_filtered[p_key] if v > 0)
    n_down = sum(1 for v in df_filtered[p_key] if v < 0)
    n_flat = sum(1 for v in df_filtered[p_key] if v == 0)
    best_stock = df_filtered.iloc[0] if not df_filtered.empty else None
    worst_stock = df_filtered.iloc[-1] if not df_filtered.empty else None
    
    now_msk = datetime.datetime.now().strftime("%d.%m.%Y, %H:%M MSK")
    st.caption(
        f"⏱️ **Период: {period}** │ Обновление: {now_msk} │ "
        f"🟢 Рост: **{n_up}** │ 🔴 Снижение: **{n_down}** │ ⚪ Без изм.: **{n_flat}**"
    )

    if df_filtered.empty:
        st.warning("По заданным фильтрам бумаг не найдено.")
        return

    # РЕЖИМ 1: ПЛИТОЧНАЯ ТЕПЛОВАЯ КАРТА (КАК НА СКРИНШОТЕ)
    if view_mode == "🟩 Плитки":
        is_large = (tile_size == "🔍 Крупные")
        grid_class = "size-large" if is_large else "size-compact"
        card_class = "m-card-large" if is_large else "m-card-compact"

        cards_parts = [
            '<div class="market-dark-canvas">'
            '<div class="market-section-title">📈 АКЦИИ (ТЕПЛОВАЯ КАРТА РЫНКА MOEX)</div>'
            f'<div class="market-section-sub">Сортировка по доходности за {period.lower()} (лидеры роста → аутсайдеры)</div>'
            f'<div class="market-tiles-grid {grid_class}">'
        ]
        
        for _, row in df_filtered.iterrows():
            t = row["ticker"]
            name = row["name"]
            ret_val = row[p_key]
            price_val = _format_price_ru(row["price"])
            css_class, badge_color = _get_tile_css_class(ret_val)
            
            # Знак процента
            if ret_val > 0:
                ret_str = f"+{ret_val:.1f}%".replace(".", ",")
            elif ret_val < 0:
                ret_str = f"{ret_val:.1f}%".replace(".", ",")
            else:
                ret_str = "0,0%"
                
            is_in_port = my_portfolio_tickers and t in my_portfolio_tickers
            port_star = '<span class="portfolio-star" title="В вашем портфеле">★ </span>' if is_in_port else ''
            
            tooltip_txt = f"{name} ({t}) | {row['sector']} | Цена: {price_val} ₽ | {p_key}: {ret_str}"
            
            cards_parts.append(
                f'<div class="{card_class} {css_class}" title="{tooltip_txt}">'
                f'<div class="m-top">'
                f'<span class="m-name">{port_star}{name}</span>'
                f'<span class="m-badge" style="color: {badge_color};">{ret_str}</span>'
                f'</div>'
                f'<div class="m-bottom">'
                f'<span class="m-price">{price_val} ₽</span>'
                f'<span class="m-ticker">{t}</span>'
                f'</div>'
                f'</div>'
            )
            
        cards_parts.append('</div></div>')
        st.markdown("".join(cards_parts), unsafe_allow_html=True)
        
    # РЕЖИМ 2: ДЕТАЛЬНАЯ ТАБЛИЦА СКРИНЕРА
    else:
        st.markdown("##### 📋 Детальная динамика по всем горизонтам инвестирования")
        disp_df = df_filtered[["ticker", "name", "sector", "price", "1D", "1W", "1M", "3M", "YTD", "val_mln"]].copy()
        disp_df.columns = [
            "Тикер", "Компания", "Сектор", "Цена (₽)",
            "1 День (%)", "1 Неделя (%)", "1 Месяц (%)", "1 Квартал (%)", "С начала года (YTD %)",
            "Оборот (млн ₽)"
        ]
        
        st.dataframe(
            disp_df,
            column_config={
                "Цена (₽)": st.column_config.NumberColumn(format="%.2f ₽"),
                "1 День (%)": st.column_config.NumberColumn(format="%+.1f%%"),
                "1 Неделя (%)": st.column_config.NumberColumn(format="%+.1f%%"),
                "1 Месяц (%)": st.column_config.NumberColumn(format="%+.1f%%"),
                "1 Квартал (%)": st.column_config.NumberColumn(format="%+.1f%%"),
                "С начала года (YTD %)": st.column_config.NumberColumn(format="%+.1f%%"),
                "Оборот (млн ₽)": st.column_config.NumberColumn(format="%.1f млн ₽")
            },
            use_container_width=True,
            hide_index=True
        )
