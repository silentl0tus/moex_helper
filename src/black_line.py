"""
Модуль расчета фундаментальной справедливой стоимости ("Чёрная линия" / Black Line / Intrinsic Value)
и отрисовки графиков котировок с наложением линии мультипликаторной оценки.

"Чёрная линия" (Invisible / Black Line) — классическая концепция стоимостного инвестирования (Бенджамин Грэм, 
Майрон Гордон, DDM, NAV), представляющая собой внутреннюю справедливую цену бизнеса, 
рассчитанную исключительно из финансовых отчетов и фундаментальных мультипликаторов компании (P/E, P/BV, ROE, 
Debt/EBITDA, Темп роста выручки, Ключевая ставка ЦБ РФ).
- Если биржевая цена ниже Чёрной линии — бумага находится в зоне недооценки с запасом прочности (Margin of Safety).
- Если биржевая цена выше Чёрной линии — рынок перегрет (зона переоценки).
"""

from __future__ import annotations

import datetime
from typing import Any, Dict, Optional, Tuple

import altair as alt
import numpy as np
import pandas as pd
import requests
import streamlit as st

# =====================================================================
# СЕКТОРНЫЕ СПРАВОЧНИКИ
# =====================================================================
BANK_TICKERS = {"SBER", "SBERP", "T", "VTBR", "BSPB", "SVCB", "CBOM", "RENI"}
CYCLICAL_TICKERS = {"CHMF", "NLMK", "MAGN", "ALRS", "RASP", "SELG", "UGLD", "UGC"}
HOLDING_TICKERS = {"SNGS", "SNGSP", "AFKS", "SFIN", "ENPG", "GAZP"}
IT_TICKERS = {"YDEX", "OZON", "POSI", "ASTR", "HEAD", "DIAS", "IVAT", "SOFL", "VKCO"}
OIL_TICKERS = {"LKOH", "ROSN", "NVTK", "TATN", "TATNP", "SIBN", "RNFT", "TRNFP", "BANE", "BANEP"}
GOLD_TICKERS = {"PLZL", "SELG", "UGLD", "UGC", "GOLD"}
CONSUMER_TICKERS = {"MGNT", "FIVE", "X5", "BELU", "NOVA", "AQUA", "MDMG", "WUSH", "FIXP"}
TOXIC_TICKERS = {"PIKK", "SMLT", "EUTR", "QIWI", "POLY", "SGZH", "MTLR", "MTLRP", "ORUP", "OBUV", "RUGR"}

# Корректировки сплитов (BELU/NOVA сплит 1:8 от 20.08.2024 и др.)
CANDLE_SPLITS: Dict[str, list[Tuple[str, float]]] = {
    "BELU": [("2024-08-20", 8.0)],
    "NOVA": [("2024-08-20", 8.0)],
}


# =====================================================================
# РАСЧЕТ ЧЕРНОЙ ЛИНИИ (FUNDAMENTAL FAIR PRICE)
# =====================================================================
def calculate_black_line_valuation(
    ticker: str,
    price: float,
    pe: Optional[float] = None,
    pb: Optional[float] = None,
    roe: Optional[float] = None,
    debt_ebitda: Optional[float] = None,
    rev_growth: Optional[float] = None,
    div_rub: Optional[float] = None,
    key_rate: float = 16.0,
) -> Dict[str, Any]:
    """
    Рассчитывает справедливую цену ("Чёрную линию") на основе фундаментальных мультипликаторов.
    
    Модели:
    1. Банки: Модель Гордона Justified P/BV = ROE / (Key_Rate * 0.6 + 6.0%) -> Fair = BVPS * P/BV_justified.
    2. Холдинги / Кубышка: Дисконтированный NAV (Net Asset Value) с учетом холдингового дисконта.
    3. IT / Рост: PEG-модель на основе темпов роста выручки и скорректированного P/E.
    4. Цикличные металлурги: Нормализованный P/BV через экономический цикл.
    5. Потребительский сектор / Дивидендные фишки: DDM (Dividend Discount Model) / FCF Yield.
    6. Реальный сектор: Адаптированная формула Грэма (RU 8x) + Скорректированный P/E с поправкой на долг.
    7. Токсичные / Дистресс: Ликвидационная стоимость с глубоким дисконтом (0.25x BV).
    """
    ticker_clean = str(ticker).upper().strip()
    
    # Защита от нулевой/отрицательной цены
    market_price = float(price) if price and not np.isnan(price) and price > 0 else 1.0
    
    # Безопасная очистка мультипликаторов
    pe_val = float(pe) if pe is not None and not np.isnan(pe) else 6.0
    pb_val = float(pb) if pb is not None and not np.isnan(pb) else 1.0
    roe_val = float(roe) if roe is not None and not np.isnan(roe) else 15.0
    debt_val = float(debt_ebitda) if debt_ebitda is not None and not np.isnan(debt_ebitda) else 1.0
    growth_val = float(rev_growth) if rev_growth is not None and not np.isnan(rev_growth) else 5.0
    div_val = float(div_rub) if div_rub is not None and not np.isnan(div_rub) else 0.0

    # Расчет базовых удельных величин
    eps = (market_price / pe_val) if (pe_val > 0 and pe_val < 100) else 0.0
    bvps = (market_price / pb_val) if (pb_val > 0) else 0.0

    model_name = ""
    fair_price = market_price
    formula_latex = ""
    thesis = ""

    # -------------------------------------------------------------
    # 1. ТОКСИЧНЫЕ И ПРЕДБАНКРОТНЫЕ АКТИВЫ (Дистресс-оценка)
    # -------------------------------------------------------------
    if ticker_clean in TOXIC_TICKERS or debt_val > 5.0 or (roe_val < -20.0 and debt_val > 3.0):
        model_name = "Дистресс / Ликвидационная стоимость (0.25x BV)"
        base_bvps = bvps if bvps > 0 else market_price * 0.3
        fair_price = max(0.5, base_bvps * 0.25)
        formula_latex = r"P_{fair} = BVPS \times 0.25"
        thesis = "Компания перегружена долгами или находится в зоне риска санации/допэмиссии. Справедливая оценка ограничена ликвидационным дисконтом."

    # -------------------------------------------------------------
    # 2. ФИНАНСОВЫЙ СЕКТОР / БАНКИ (Justified P/BV Гордона)
    # -------------------------------------------------------------
    elif ticker_clean in BANK_TICKERS:
        # Стоимость собственного капитала банков в РФ при ключевой ставке
        cost_of_equity = (key_rate * 0.60 + 6.0)  # Например, при ставке 16% -> 15.6%
        norm_roe = max(5.0, min(36.0, roe_val))
        justified_pb = norm_roe / cost_of_equity
        justified_pb = max(0.65, min(2.30, justified_pb))
        
        base_bvps = bvps if bvps > 0 else market_price
        fair_price = base_bvps * justified_pb
        model_name = f"Гордон Justified P/BV ({justified_pb:.2f}x по ROE {norm_roe:.1f}%)"
        formula_latex = r"P_{fair} = BVPS \times \frac{ROE}{r_e}, \quad r_e = \text{KeyRate} \times 0.6 + 6\%"
        thesis = f"Банк оценивается по эффективности капитала: при ROE {norm_roe:.1f}% и стоимости фондирования {cost_of_equity:.1f}% справедливый мультипликатор P/BV составляет {justified_pb:.2f}x."

    # -------------------------------------------------------------
    # 3. ХОЛДИНГИ И КОМПАНИИ С КУБЫШКОЙ (Дисконтированный NAV)
    # -------------------------------------------------------------
    elif ticker_clean in HOLDING_TICKERS:
        base_bvps = bvps if bvps > 0 else market_price
        # Для Газпрома балансовая стоимость газопроводов гигантская (P/BV ~ 0.15-0.2), дисконт 0.40x BV
        discount = 0.40 if ticker_clean == "GAZP" else 0.80
        fair_price = base_bvps * discount
        model_name = f"Дисконтированный NAV / Чистые активы ({discount:.2f}x BV)"
        formula_latex = rf"P_{{fair}} = BVPS \times {discount:.2f}"
        thesis = f"Прибыль искажена переоценками дочерних структур или валютной кубышки. Фундаментальная оценка рассчитывается от стоимости чистых активов с холдинговым дисконтом {(1 - discount) * 100:.0f}%."

    # -------------------------------------------------------------
    # 4. IT И ВЫСОКОТЕХНОЛОГИЧНЫЙ СЕКТОР (PEG Growth Model)
    # -------------------------------------------------------------
    elif ticker_clean in IT_TICKERS:
        target_pe = max(11.0, min(26.0, 10.0 + max(0.0, growth_val) * 0.35))
        if eps > 0:
            fair_price = eps * target_pe
        else:
            fair_price = market_price * (1.0 + min(max(growth_val, 0.0), 50.0) / 100.0)
        model_name = f"PEG Growth Model (Оценка {target_pe:.1f}x P/E при росте +{growth_val:.1f}%)"
        formula_latex = r"P_{fair} = EPS \times P/E_{fair}, \quad P/E_{fair} = 10.0 + 0.35 \times \text{Growth}"
        thesis = f"Компания реинвестирует прибыль в экспансию и захват доли рынка. Справедливый P/E составляет {target_pe:.1f}x с учетом темпа роста выручки +{growth_val:.1f}%."

    # -------------------------------------------------------------
    # 5. ЦИКЛИЧНЫЕ МЕТАЛЛУРГИ НА ДНЕ ЦИКЛА (Normalized P/BV)
    # -------------------------------------------------------------
    elif ticker_clean in CYCLICAL_TICKERS:
        base_bvps = bvps if bvps > 0 else market_price
        # Металлурги с чистым долгом около нуля заслуживают премию к капиталу
        debt_bonus = 0.20 if debt_val <= 0.8 else (-0.20 if debt_val > 1.8 else 0.0)
        target_pb = 1.35 + debt_bonus
        fair_price = base_bvps * target_pb
        model_name = f"Нормализованный P/BV ({target_pb:.2f}x через экономический цикл)"
        formula_latex = rf"P_{{fair}} = BVPS \times {target_pb:.2f}"
        thesis = f"В цикличных отраслях прибыль колеблется. Оценка ведется через нормализованный капитал через весь цикл (P/BV {target_pb:.2f}x) с учетом долговой нагрузки {debt_val:.1f}x."

    # -------------------------------------------------------------
    # 6. ЗОЛОТОДОБЫТЧИКИ (Commodity / FCF Valuation)
    # -------------------------------------------------------------
    elif ticker_clean in GOLD_TICKERS:
        target_pe = max(6.0, min(10.0, 7.5 + (roe_val - key_rate) * 0.05))
        if eps > 0:
            fair_price = eps * target_pe
        else:
            fair_price = market_price * 1.10
        model_name = f"Мультипликатор золота ({target_pe:.1f}x P/E)"
        formula_latex = r"P_{fair} = EPS \times P/E_{fair}"
        thesis = f"Сверхнизкая себестоимость добычи и защита от девальвации рубля. Справедливый целевой P/E составляет {target_pe:.1f}x."

    # -------------------------------------------------------------
    # 7. ПОТРЕБИТЕЛЬСКИЙ СЕКТОР С ИСКАЖЕННЫМ БАЛАНСОМ (MGNT, etc.)
    # -------------------------------------------------------------
    elif ticker_clean in CONSUMER_TICKERS and (pe_val <= 0 or pb_val <= 0):
        if div_val > 0:
            required_yield = max(key_rate * 0.65, 10.0) / 100.0
            fair_price = div_val / required_yield
            model_name = f"Дивидендная модель DDM (дивы {div_val:.1f} ₽ / требуемая доходность {required_yield * 100:.1f}%)"
            formula_latex = r"P_{fair} = \frac{\text{Div}}{r_{req}}"
            thesis = f"Баланс искажен арендными обязательствами МСФО 16. Оценка строится на стабильном денежном потоке и дивидендах {div_val:.1f} ₽."
        else:
            fair_price = market_price * 1.15
            model_name = "Оценка по операционному денежному потоку (+15% буфер)"
            formula_latex = r"P_{fair} = P_{market} \times 1.15"
            thesis = "Оценка опирается на стабильный потребительский денежный поток с консервативной премией."

    # -------------------------------------------------------------
    # 8. БАЗОВЫЙ РЕАЛЬНЫЙ СЕКТОР (Нефть, газ, электроэнергетика, телекомы)
    # -------------------------------------------------------------
    else:
        # Скорректированный целевой P/E для РФ
        target_pe = max(4.0, min(8.5, 5.5 + (growth_val * 0.06) + (roe_val - key_rate) * 0.08 - max(0.0, debt_val) * 0.30))
        pe_price = (eps * target_pe) if eps > 0 else market_price
        
        # Адаптированная формула Грэма под российский рынок: 
        # Benjamin Graham использовал 22.5 для США (PE 15 * PB 1.5). 
        # В РФ средний PE 5.5 и PB 1.1 -> множитель 6.0-8.0x.
        ru_graham_mult = 7.0
        graham_price = np.sqrt(max(0.0, ru_graham_mult * eps * bvps)) if (eps > 0 and bvps > 0) else pe_price
        
        # Взвешенная фундаментальная стоимость
        fair_price = 0.5 * pe_price + 0.5 * graham_price
        
        # Корректировка на долговую нагрузку
        if debt_val < 0.2:
            fair_price *= 1.08  # Бонус за чистый отрицательный долг
        elif debt_val > 2.0:
            fair_price *= (1.0 / (1.0 + (debt_val - 2.0) * 0.15))
            
        model_name = f"Грэм (RU 7x) + Скорр. P/E ({target_pe:.1f}x)"
        formula_latex = r"P_{fair} = 0.5 \times (EPS \times P/E_{fair}) + 0.5 \times \sqrt{7.0 \times EPS \times BVPS}"
        thesis = f"Классический стоимостной анализ: синтез формулы Грэма и скорректированного мультипликатора P/E ({target_pe:.1f}x) с учетом долговой нагрузки ({debt_val:.1f}x)."

    # Итоговый срез и запас прочности
    fair_price = max(0.1, round(fair_price, 2))
    upside_pct = round(((fair_price - market_price) / market_price) * 100.0, 1)

    # Определение инвестиционной зоны
    if upside_pct >= 30.0:
        valuation_zone = "🟢 Глубокая недооценка (Strong Buy / Высокий Margin of Safety)"
        zone_color = "#00C853"
        action = "🟢 Накапливать позицию (Отличная точка входа)"
    elif upside_pct >= 10.0:
        valuation_zone = "🟢 Умеренная недооценка (Buy / Запас прочности)"
        zone_color = "#64DD17"
        action = "🟢 Покупать / Увеличивать долю"
    elif upside_pct >= -10.0:
        valuation_zone = "⚪ Справедливо оценено рынком (Fair Value / Hold)"
        zone_color = "#FFD600"
        action = "⚪ Удерживать текущую позицию"
    elif upside_pct >= -25.0:
        valuation_zone = "🟠 Умеренная переоценка (Take Profit / Hold)"
        zone_color = "#FF9100"
        action = "🟠 Рассмотреть частичную фиксацию прибыли"
    else:
        valuation_zone = "🔴 Сильная переоценка (Overvalued / Sell)"
        zone_color = "#D50000"
        action = "🔴 Продать / Переложиться в недооцененные активы"

    return {
        "ticker": ticker_clean,
        "market_price": round(market_price, 2),
        "fair_price": fair_price,
        "upside_pct": upside_pct,
        "margin_of_safety": upside_pct,
        "valuation_zone": valuation_zone,
        "zone_color": zone_color,
        "action": action,
        "model_name": model_name,
        "formula_latex": formula_latex,
        "thesis": thesis,
        "eps": round(eps, 2),
        "bvps": round(bvps, 2),
        "pe": round(pe_val, 2),
        "pb": round(pb_val, 2),
        "roe": round(roe_val, 1),
        "debt_ebitda": round(debt_val, 2),
        "rev_growth": round(growth_val, 1),
    }


# =====================================================================
# ЗАГРУЗКА ИСТОРИЧЕСКИХ СВЕЧЕЙ (MOEX ISS API)
# =====================================================================
@st.cache_data(ttl=900)
def fetch_stock_candles(ticker: str, days: int = 365) -> pd.DataFrame:
    """
    Запрашивает дневные свечи котировок с Московской Биржи (MOEX ISS)
    с автоматической нормализацией корпоративных сплитов (BELU/NOVA и др.).
    """
    ticker_clean = str(ticker).upper().strip()
    start_date = (datetime.date.today() - datetime.timedelta(days=days)).strftime("%Y-%m-%d")
    url = f"https://iss.moex.com/iss/engines/stock/markets/shares/boards/TQBR/securities/{ticker_clean}/candles.json"
    
    try:
        r = requests.get(
            url,
            params={"interval": 24, "from": start_date, "iss.meta": "off"},
            timeout=8,
        )
        if r.status_code != 200:
            return pd.DataFrame()
            
        data = r.json()
        cols = data.get("candles", {}).get("columns", [])
        rows = data.get("candles", {}).get("data", [])
        
        if not cols or not rows:
            return pd.DataFrame()
            
        df = pd.DataFrame(rows, columns=cols)
        df["date"] = pd.to_datetime(df["begin"])
        
        # Преобразование числовых колонок
        for num_col in ["open", "high", "low", "close", "volume", "value"]:
            if num_col in df.columns:
                df[num_col] = pd.to_numeric(df[num_col], errors="coerce")
                
        # Нормализация сплитов (например, BELU 1:8 в августе 2024)
        splits = CANDLE_SPLITS.get(ticker_clean, [])
        for split_date_str, split_ratio in splits:
            split_dt = pd.to_datetime(split_date_str)
            pre_split_mask = df["date"] < split_dt
            for p_col in ["open", "high", "low", "close"]:
                if p_col in df.columns:
                    df.loc[pre_split_mask, p_col] = df.loc[pre_split_mask, p_col] / split_ratio
                    
        # Расчет скользящих средних
        df["sma_50"] = df["close"].rolling(window=50, min_periods=10).mean()
        df["sma_200"] = df["close"].rolling(window=200, min_periods=30).mean()
        
        return df.sort_values(by="date").reset_index(drop=True)
    except Exception as e:
        st.warning(f"Ошибка загрузки истории котировок {ticker_clean}: {e}")
        return pd.DataFrame()


# =====================================================================
# ОТРИСОВКА ИНТЕРАКТИВНОГО ГРАФИКА В ALTAIR
# =====================================================================
def create_black_line_chart(
    candles_df: pd.DataFrame,
    fair_info: Dict[str, Any],
    show_black_line: bool = True,
    height: int = 420,
) -> alt.Chart:
    """
    Строит график котировок акции с наложением Чёрной Линии (Black Line) и зон Margin of Safety.
    Поддерживает динамическое включение/выключение Чёрной линии.
    """
    if candles_df.empty:
        # Пустой заглушечный чарт при отсутствии данных
        return alt.Chart(pd.DataFrame({"msg": ["Нет данных"]})).mark_text().encode(text="msg:N")

    df_chart = candles_df.copy()
    fair_price = fair_info.get("fair_price", 0.0)
    ticker = fair_info.get("ticker", "")
    upside_pct = fair_info.get("upside_pct", 0.0)

    df_chart["fair_price"] = fair_price
    df_chart["fair_upper"] = fair_price * 1.15
    df_chart["fair_lower"] = fair_price * 0.85
    df_chart["diff_pct"] = ((fair_price - df_chart["close"]) / df_chart["close"] * 100.0).round(1)
    df_chart["date_str"] = df_chart["date"].dt.strftime("%Y-%m-%d")

    # Базовая ось X
    x_axis = alt.X("date:T", title="Дата", axis=alt.Axis(format="%b %Y", labelAngle=-30))

    # Линия цены котировок (Close Price)
    price_line = alt.Chart(df_chart).mark_line(
        color="#1E88E5",
        strokeWidth=2.2,
    ).encode(
        x=x_axis,
        y=alt.Y(
            "close:Q",
            title=f"Цена акции {ticker} (₽)",
            scale=alt.Scale(zero=False, padding=15),
        ),
        tooltip=[
            alt.Tooltip("date_str:N", title="Дата"),
            alt.Tooltip("close:Q", title="Цена закрытия (₽)", format=".2f"),
            alt.Tooltip("open:Q", title="Открытие (₽)", format=".2f"),
            alt.Tooltip("high:Q", title="Максимум (₽)", format=".2f"),
            alt.Tooltip("low:Q", title="Минимум (₽)", format=".2f"),
            alt.Tooltip("sma_50:Q", title="SMA 50 (₽)", format=".1f"),
            alt.Tooltip("sma_200:Q", title="SMA 200 (₽)", format=".1f"),
        ],
    )

    # Скользящие средние SMA 50 и SMA 200
    sma50_line = alt.Chart(df_chart).mark_line(
        color="#FFA726",
        strokeWidth=1.5,
        strokeDash=[5, 3],
    ).encode(
        x="date:T",
        y="sma_50:Q",
        tooltip=[
            alt.Tooltip("date_str:N", title="Дата"),
            alt.Tooltip("sma_50:Q", title="SMA 50 (₽)", format=".2f"),
        ],
    )

    sma200_line = alt.Chart(df_chart).mark_line(
        color="#AB47BC",
        strokeWidth=1.5,
        strokeDash=[3, 3],
    ).encode(
        x="date:T",
        y="sma_200:Q",
        tooltip=[
            alt.Tooltip("date_str:N", title="Дата"),
            alt.Tooltip("sma_200:Q", title="SMA 200 (₽)", format=".2f"),
        ],
    )

    layers = [price_line, sma50_line, sma200_line]

    # СЛОЙ: ЧЁРНАЯ ЛИНИЯ (BLACK LINE / FAIR VALUE)
    if show_black_line and fair_price > 0:
        # 1. Зона коридора справедливой стоимости (±15% Margin of Safety)
        corridor_color = "#00E676" if upside_pct > 0 else "#FF5252"
        corridor = alt.Chart(df_chart).mark_area(
            opacity=0.10,
            color=corridor_color,
        ).encode(
            x="date:T",
            y="fair_lower:Q",
            y2="fair_upper:Q",
        )
        layers.insert(0, corridor)

        # 2. Сама ЧЁРНАЯ ЛИНИЯ: выразительная темная линия со штриховкой
        # Для отличной видимости как на светлой, так и на темной теме Streamlit
        black_line_glow = alt.Chart(df_chart).mark_line(
            color="#FFFFFF",
            strokeWidth=4.5,
            opacity=0.35,
        ).encode(
            x="date:T",
            y="fair_price:Q",
        )

        black_line = alt.Chart(df_chart).mark_line(
            color="#111111",
            strokeWidth=3.0,
            strokeDash=[8, 4],
        ).encode(
            x="date:T",
            y="fair_price:Q",
            tooltip=[
                alt.Tooltip("date_str:N", title="Дата"),
                alt.Tooltip("fair_price:Q", title="Чёрная линия (Fair Value, ₽)", format=".2f"),
                alt.Tooltip("diff_pct:Q", title="Отклонение от рынка (%)", format="+.1f"),
            ],
        )

        # 3. Текстовая плашка у последнего бара
        latest_date = df_chart["date"].iloc[-1]
        label_df = pd.DataFrame([{
            "date": latest_date,
            "fair_price": fair_price,
            "label": f"🎯 Чёрная линия: {fair_price:.1f} ₽ ({upside_pct:+.1f}%)",
        }])

        text_label = alt.Chart(label_df).mark_text(
            align="right",
            dx=-10,
            dy=-12,
            fontSize=12,
            fontWeight="bold",
            color="#111111",
        ).encode(
            x="date:T",
            y="fair_price:Q",
            text="label:N",
        )

        layers.extend([black_line_glow, black_line, text_label])

    # Сборка финального графика
    final_chart = alt.layer(*layers).properties(
        height=height,
    ).configure_axis(
        gridColor="#E0E0E0",
        gridOpacity=0.4,
    ).interactive(
        bind_y=False,
    )

    return final_chart


# =====================================================================
# ГОТОВЫЙ КОМПОНЕНТ ДЛЯ STREAMLIT С ПЕРЕКЛЮЧАТЕЛЕМ
# =====================================================================
def render_black_line_widget(
    ticker: str,
    current_price: float,
    fund_row: Optional[pd.Series] = None,
    key_rate: float = 16.0,
    default_show: bool = True,
    key_prefix: str = "bl",
) -> None:
    """
    Универсальный интерактивный виджет для Streamlit:
    - Интерактивный тумблер включения/выключения Чёрной линии
    - Метрики: Справедливая цена, Рынок, Margin of Safety, Инвестиционная зона
    - График котировок с наложением Чёрной линии
    - Сворачиваемая математическая расшифровка расчета
    """
    ticker_clean = str(ticker).upper().strip()
    
    # Извлечение параметров из фундаментальной строки
    pe = None
    pb = None
    roe = None
    debt = None
    growth = None
    div_rub = None
    
    if fund_row is not None and not fund_row.empty:
        pe = fund_row.get("P_E")
        pb = fund_row.get("P_BV")
        roe = fund_row.get("ROE_%")
        debt = fund_row.get("Debt_EBITDA")
        growth = fund_row.get("Rev_Growth_%")
        div_rub = fund_row.get("Div_RUB")

    # Загрузка свечей котировок с МосБиржи
    with st.spinner(f"Загрузка истории торгов {ticker_clean} с MOEX ISS..."):
        candles_df = fetch_stock_candles(ticker_clean, days=365)

    # Если цена не передана или <= 0, берем последнее закрытие из истории
    effective_price = current_price
    if (effective_price is None or effective_price <= 0) and not candles_df.empty:
        effective_price = float(candles_df["close"].iloc[-1])
    if effective_price is None or effective_price <= 0:
        effective_price = 100.0

    # Расчет Чёрной линии
    fair_info = calculate_black_line_valuation(
        ticker=ticker_clean,
        price=effective_price,
        pe=pe,
        pb=pb,
        roe=roe,
        debt_ebitda=debt,
        rev_growth=growth,
        div_rub=div_rub,
        key_rate=key_rate,
    )

    fair_p = fair_info["fair_price"]
    market_p = fair_info["market_price"]
    upside = fair_info["upside_pct"]
    zone_label = fair_info["valuation_zone"]
    model_name = fair_info["model_name"]
    formula_latex = fair_info["formula_latex"]
    thesis = fair_info["thesis"]

    # 1. Верхняя панель управления: Интерактивный тумблер ON/OFF
    ctrl_col1, ctrl_col2 = st.columns([3, 1])
    with ctrl_col1:
        st.markdown(f"#### 📈 {ticker_clean} — Котировки MOEX vs Чёрная Линия (Fair Value)")
    with ctrl_col2:
        show_black_line = st.toggle(
            "🖤 Показать Чёрную Линию",
            value=default_show,
            key=f"{key_prefix}_toggle_{ticker_clean}",
            help="Включает или выключает отображение линии фундаментальной справедливой стоимости (Black Line / Fair Value), рассчитанной из мультипликаторов компании.",
        )

    # 2. Четыре ключевые метрики
    m_col1, m_col2, m_col3, m_col4 = st.columns(4)
    with m_col1:
        st.metric(
            "Рыночная цена (MOEX)",
            f"{market_p:,.2f} ₽",
            help="Текущая котировка акции на МосБирже в режиме Т+1",
        )
    with m_col2:
        if show_black_line:
            st.metric(
                "🎯 Чёрная линия (Fair Value)",
                f"{fair_p:,.2f} ₽",
                f"{upside:+.1f}% к рынку",
                delta_color="normal" if upside >= 0 else "inverse",
                help="Справедливая внутренняя цена акции, рассчитанная по финансовым мультипликаторам",
            )
        else:
            st.metric("🎯 Чёрная линия", "Отключена", "Включите тумблер")
            
    with m_col3:
        if show_black_line:
            st.metric(
                "🛡️ Запас прочности (Margin of Safety)",
                f"{abs(upside):.1f}%",
                "Недооценка (Buy)" if upside > 0 else "Переоценка (Sell)",
                delta_color="normal" if upside >= 0 else "inverse",
                help="Величина дисконта к справедливой стоимости по Бенджамину Грэму",
            )
        else:
            st.metric("🛡️ Запас прочности", "—")
            
    with m_col4:
        st.metric(
            "Статус оценки",
            "🟢 BUY" if upside >= 10 else ("⚪ HOLD" if upside >= -10 else "🔴 SELL"),
            zone_label.split(" (")[0],
            help="Рекомендованное действие на основе соотношения рынка и внутренней стоимости",
        )

    # 3. Отрисовка графика

    if not candles_df.empty:
        chart = create_black_line_chart(
            candles_df=candles_df,
            fair_info=fair_info,
            show_black_line=show_black_line,
            height=420,
        )
        st.altair_chart(chart, use_container_width=True)
        st.caption("Легенда: 🔵 Котировки закрытия (Close) | 🟠 SMA 50 | 🟣 SMA 200 | 🖤 **Чёрная линия** (Справедливая фундаментальная цена) | 🟩 Запас прочности (Margin of Safety ±15%)")
    else:
        st.info(f"Исторические свечи для {ticker_clean} временно недоступны на MOEX ISS.")

    # 4. Методологическая расшифровка расчета
    if show_black_line:
        with st.expander(f"🧮 Методология и формула расчета Чёрной линии для {ticker_clean}", expanded=False):
            st.markdown(f"**Примененная модель:** `{model_name}`")
            if formula_latex:
                st.latex(formula_latex)
            st.write(f"💡 **Обоснование:** {thesis}")
            
            c_f1, c_f2, c_f3, c_f4, c_f5 = st.columns(5)
            c_f1.metric("EPS (Прибыль/акцию)", f"{fair_info['eps']:.2f} ₽" if fair_info['eps'] > 0 else "Н/Д")
            c_f2.metric("BVPS (Капитал/акцию)", f"{fair_info['bvps']:.2f} ₽" if fair_info['bvps'] > 0 else "Н/Д")
            c_f3.metric("P/E (Текущий)", f"{fair_info['pe']:.2f}x")
            c_f4.metric("P/BV (Текущий)", f"{fair_info['pb']:.2f}x")
            c_f5.metric("ROE (Рентабельность)", f"{fair_info['roe']:.1f}%")
