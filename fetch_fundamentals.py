"""
fetch_fundamentals.py
---------------------
Standalone-скрипт для парсинга фундаментальных данных с smart-lab.ru.
Запускается GitHub Actions каждый будний день в 09:00 МСК.
Результат сохраняется в fundamentals_cache.csv и коммитится в репозиторий.
Streamlit Cloud читает CSV напрямую из репозитория — без прокси и без вашего ПК.
"""

import time
import random
import logging
from io import StringIO
from pathlib import Path

import requests
import pandas as pd

# ── Логгирование ─────────────────────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger(__name__)

# ── Конфигурация ──────────────────────────────────────────────────────────────

# Полный список тикеров для парсинга (расширьте при необходимости)
TICKER_LIST = [
    "MGNT", "SBER", "ROSN", "NMTP", "SVCB", "T", "SIBN", "BELU", "CHMF", "NLMK",
    "SNGS", "TRNFP", "GAZP", "LKOH", "PLZL", "TATN", "NVTK", "GMKN", "AFKS",
    "MOEX", "IRAO", "VTBR", "POSI", "ASTR", "HEAD", "X5", "ALRS", "PHOR",
    "MTSS", "RTKM", "FEES", "UPRO", "AFLT", "MAGN", "VKCO", "OZON", "BSPB",
    "SFIN", "ENPG", "SELG", "RUAL", "CBOM", "SOFL", "DIAS", "FLOT", "MTLR",
    "SNGS", "SNGSP", "RNFT", "MDMG", "NMTP", "RENI", "OZPH", "BELU", "RAGR",
    "CNRU", "DOMRF", "IVAT", "PRMD", "SGZH", "WUSH", "TRMK",
]
# Убираем дубликаты и сортируем
TICKER_LIST = sorted(set(TICKER_LIST))

# Маппинг тикеров MOEX → тикеры smart-lab (если отличаются)
SMARTLAB_MAP = {
    "YDEX": "YNDX",
    "T": "TCSG",
}

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/125.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "ru-RU,ru;q=0.9,en;q=0.8",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
}

OUTPUT_PATH = Path(__file__).parent / "fundamentals_cache.csv"

# ── Парсинг одного тикера ─────────────────────────────────────────────────────

def parse_ticker(ticker: str) -> dict | None:
    """Парсит страницу smart-lab.ru и возвращает словарь с мультипликаторами."""
    smartlab_ticker = SMARTLAB_MAP.get(ticker.upper(), ticker.upper())
    url = f"https://smart-lab.ru/q/{smartlab_ticker}/f/y/"

    try:
        response = requests.get(url, headers=HEADERS, timeout=15)
        response.raise_for_status()
    except requests.RequestException as e:
        log.warning(f"  ✗ {ticker}: сетевая ошибка — {e}")
        return None

    try:
        tables = pd.read_html(StringIO(response.text))
    except ValueError:
        log.warning(f"  ✗ {ticker}: таблицы не найдены на странице")
        return None

    if not tables:
        return None

    df = tables[0]

    # Удаляем LTM-колонку (экстраполяция, часто искажена)
    ltm_cols = [c for c in df.columns if df[c].astype(str).str.contains("LTM", case=False).any()]
    if ltm_cols:
        df = df.drop(columns=ltm_cols)

    df = df.rename(columns={df.columns[0]: "Metric"})
    df = df[[c for c in df.columns if c != "?"]]

    # Чистим числа от пробелов и процентов
    for col in df.columns:
        if col != "Metric":
            df[col] = df[col].astype(str).str.replace(r"[\s%]", "", regex=True)

    df = df.drop_duplicates(subset=["Metric"], keep="first")
    df = df.set_index("Metric").T

    for col in df.columns:
        df[col] = pd.to_numeric(df[col], errors="coerce")

    cols = {str(c).lower(): c for c in df.columns}

    def find(keywords: list[str]):
        for kw in keywords:
            col = next((v for k, v in cols.items() if kw in k), None)
            if col and not df[col].dropna().empty:
                return df[col].dropna().iloc[-1]
        return None

    roe   = find(["roe"])
    pe    = find(["p/e", "p / e"])
    pbv   = find(["p/bv", "p / bv"])
    debt  = find(["долг/ebitda", "debt/ebitda"])
    fcfy  = find(["доходность fcf"])
    div   = find(["дивиденд, руб"])  # только обычные акции

    # Рост выручки: считаем из двух последних значений
    rev_growth = None
    rev_col = next(
        (v for k, v in cols.items() if "выручка" in k or "чист. операц" in k or "чистый операц" in k),
        None,
    )
    if rev_col:
        rev_series = df[rev_col].dropna()
        if len(rev_series) >= 2:
            cur, prev = rev_series.iloc[-1], rev_series.iloc[-2]
            if prev != 0:
                rev_growth = round((cur - prev) / abs(prev) * 100, 2)

    # Для банков нет смысла считать Debt/EBITDA — ставим безопасную константу
    BANK_TICKERS = {"SBER", "SBERP", "VTBR", "TCSG", "BSPB", "CBOM", "T", "SVCB"}
    ZERO_DEBT_TICKERS = {"SNGS", "SNGSP"}  # отрицательный чистый долг
    if debt is None:
        if ticker.upper() in BANK_TICKERS:
            debt = 1.0
        elif ticker.upper() in ZERO_DEBT_TICKERS:
            debt = 0.0

    payload = {"ticker": ticker.upper()}
    if roe       is not None: payload["ROE_%"]        = round(float(roe),  2)
    if pe        is not None: payload["P_E"]           = round(float(pe),   2)
    if pbv       is not None: payload["P_BV"]          = round(float(pbv),  2)
    if fcfy      is not None: payload["FCF_Yield_%"]   = round(float(fcfy), 2)
    if div       is not None: payload["Div_RUB"]        = round(float(div),  4)
    if rev_growth is not None: payload["Rev_Growth_%"] = rev_growth
    if debt      is not None: payload["Debt_EBITDA"]   = round(float(debt), 2)

    return payload


# ── Основной цикл ─────────────────────────────────────────────────────────────

def main():
    log.info(f"Начинаем парсинг {len(TICKER_LIST)} тикеров…")
    results = []

    for i, ticker in enumerate(TICKER_LIST, start=1):
        log.info(f"[{i:>3}/{len(TICKER_LIST)}] {ticker}…")
        data = parse_ticker(ticker)
        if data:
            results.append(data)
            log.info(f"  ✓ {ticker}: ROE={data.get('ROE_%')}, P/E={data.get('P_E')}, Debt={data.get('Debt_EBITDA')}")
        else:
            log.warning(f"  ✗ {ticker}: данных нет")

        # Вежливая пауза: 1.5–3 сек между запросами, чтобы не получить бан
        time.sleep(random.uniform(1.5, 3.0))

    if not results:
        log.error("Не удалось получить ни одного тикера! Файл не перезаписан.")
        raise SystemExit(1)

    new_df = pd.DataFrame(results)

    # Мёржим с существующим кэшем: новые данные приоритетнее
    COLUMNS = ["ticker", "ROE_%", "P_E", "P_BV", "FCF_Yield_%", "Div_RUB", "Rev_Growth_%", "Debt_EBITDA"]
    if OUTPUT_PATH.exists():
        try:
            old_df = pd.read_csv(OUTPUT_PATH)
            merged = (
                pd.concat([new_df, old_df])
                .drop_duplicates(subset=["ticker"], keep="first")
                .reset_index(drop=True)
            )
            # Оставляем только нужные колонки (могут быть лишние)
            out_cols = [c for c in COLUMNS if c in merged.columns]
            merged = merged[out_cols]
        except Exception as e:
            log.warning(f"Не удалось прочитать старый кэш: {e}. Пишем только новые данные.")
            merged = new_df[[c for c in COLUMNS if c in new_df.columns]]
    else:
        merged = new_df[[c for c in COLUMNS if c in new_df.columns]]

    merged.to_csv(OUTPUT_PATH, index=False)
    log.info(f"✅ Готово! Обновлено {len(new_df)} тикеров, всего в кэше: {len(merged)}. → {OUTPUT_PATH}")


if __name__ == "__main__":
    main()
