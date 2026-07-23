# MOEX Helper

Инструменты для анализа акций Московской биржи: загрузка тикеров, Streamlit-дашборд портфеля и вспомогательные скрипты.

## Запуск дашборда

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements-dashboard.txt
streamlit run streamlit_project.py
```

Приложение откроется на `http://localhost:8501`.

## Структура

| Файл | Назначение |
|------|------------|
| `streamlit_project.py` | Streamlit-дашборд: котировки, фундаментал, правила портфеля |
| `requests_tickers.py` | CLI-скрипт: выводит список тикеров MOEX TQBR (1–2 эшелон) |
| `requirements-dashboard.txt` | Зависимости дашборда |

## Источник тикеров

Оба файла используют один и тот же запрос к MOEX ISS API:

- **URL:** `https://iss.moex.com/iss/engines/stock/markets/shares/boards/TQBR/securities.json`
- **Фильтр:** только акции с `LISTLEVEL` 1 или 2 (первый и второй эшелон)
- **Кэш в дашборде:** 24 часа (`@st.cache_data(ttl=86400)`)

### Проверка согласованности данных

На 24.07.2026 оба источника возвращают **217 тикеров**, списки полностью совпадают.

```bash
python requests_tickers.py
# Найдено качественных активов: 217

python -c "
import requests
url = 'https://iss.moex.com/iss/engines/stock/markets/shares/boards/TQBR/securities.json'
params = {'iss.meta': 'off', 'iss.only': 'securities', 'securities.columns': 'SECID,LISTLEVEL'}
data = requests.get(url, params=params, timeout=30).json()
tickers = sorted(r[0] for r in data['securities']['data'] if r[1] in (1, 2))
print(len(tickers), tickers[:5], '...', tickers[-3:])
"
```

Дефолтные тикеры дашборда (`SBER`, `LKOH`, `GAZP`, `YDEX`) присутствуют в общем списке.

## Изменения (2026-07-24)

### Интеграция тикеров MOEX в Streamlit-дашборд

- Добавлена функция `fetch_moex_tickers()` — загружает полный список акций TQBR 1–2 эшелона с MOEX ISS API.
- В sidebar multiselect теперь содержит все **217** тикеров вместо захардкоженных 4.
- Добавлен чекбокс **«Анализировать все тикеры»** для массового выбора (загрузка котировок может занять несколько минут).
- На главной странице — expander **«Полный список тикеров MOEX»** с таблицей всех доступных инструментов.
- Дефолтный набор (`SBER`, `LKOH`, `GAZP`, `YDEX`) сохранён как `FALLBACK_TICKERS`.

Логика `fetch_moex_tickers()` идентична `requests_tickers.py` — проверено побайтово, расхождений нет.
