# moex_helper — Карта проекта и контекст (as of `520cd63`)

> Компактный справочник для быстрого входа в разработку без повторного чтения всей кодовой базы. Рабочая ветка: `main` (`origin/main` → автодеплой на `moexelperdash.streamlit.app`).

---

## 1. Структура и точки входа

| Файл | Назначение |
| --- | --- |
| [streamlit_project.py](file:///mnt/new_volume/VS_code_base/moex_helper/streamlit_project.py) | Главный экран: общий мониторинг MOEX по умолчанию, **Светофор рынка** на 1-м экране, Командный пульт (`Продать / Купить / Рокировки`), виджет Чёрной линии, `Health_Score`, разведка рынков. |
| [1_🎯_Мастер_подбора.py](file:///mnt/new_volume/VS_code_base/moex_helper/pages/1_%F0%9F%8E%AF_%D0%9C%D0%B0%D1%81%D1%82%D0%B5%D1%80_%D0%BF%D0%BE%D0%B4%D0%B1%D0%BE%D1%80%D0%B0.py) | Скринер бумаг по `fundamentals_cache.csv` (`load_screener_data(cache_version="v3_value_income")`) с едиными правилами для структурного дисконта и `Income Reversion`. |
| [2_💬_Сентимент_и_Пульс.py](file:///mnt/new_volume/VS_code_base/moex_helper/pages/2_%F0%9F%92%AC_%D0%A1%D0%B5%D0%BD%D1%82%D0%B8%D0%BC%D0%B5%D0%BD%D1%82_%D0%B8_%D0%9F%D1%83%D0%BB%D1%8C%D1%81.py) | Настроения и сентимент (данные из `sentiment.json`). |
| [3_⏳_Бэктест_Стратегии.py](file:///mnt/new_volume/VS_code_base/moex_helper/pages/3_%E2%8F%B3_%D0%91%D1%8D%D0%BA%D1%82%D0%B5%D1%81%D1%82_%D0%A1%D1%82%D1%80%D0%B0%D1%82%D0%B5%D0%B3%D0%B8%D0%B8.py) | Исторический бэктест стратегии. |
| [4_💼_Реальный_Портфель_и_Сделки.py](file:///mnt/new_volume/VS_code_base/moex_helper/pages/4_%F0%9F%92%BC_%D0%A0%D0%B5%D0%B0%D0%BB%D1%8C%D0%BD%D1%8B%D0%B9_%D0%9F%D0%BE%D1%80%D1%82%D1%84%D0%B5%D0%BB%D1%8C_%D0%B8_%D0%A1%D0%B4%D0%B5%D0%BB%D0%BA%D0%B8.py) | Реальный портфель (MCP / Excel / ссылка): открытые позиции, зеркальный бенчмарк `MCFTRR` vs `IMOEX`, журнал всех операций (`trades`), закрытые сделки `FIFO` (`closed`), дивиденды и купоны (`events`). |
| [src/black_line.py](file:///mnt/new_volume/VS_code_base/moex_helper/src/black_line.py) | Расчёт справедливой цены (`calculate_black_line_valuation`) и интерактивный график Altair (`render_black_line_widget`). |
| [src/izi_mcp_client.py](file:///mnt/new_volume/VS_code_base/moex_helper/src/izi_mcp_client.py) | JSON-RPC клиент `izi-invest.ru/mcp`: портфели, позиции, аналитика (`get_analysis`), журнал/FIFO/дивиденды/купоны (`fetch_portfolio_ledger`), рыночный контекст (`get_market_context`). |
| [src/portfolio_importer.py](file:///mnt/new_volume/VS_code_base/moex_helper/src/portfolio_importer.py) | Импорт через `fetch_izi_mcp_portfolio`, парсинг Excel/CSV отчётов брокеров, учёт сплитов (`TRNFP`, `VTBR`, `BELU`, `NOVA`), `calculate_mirror_benchmark_timeline`, `calculate_xirr`, сквозные переносы. |
| [src/foundry_client.py](file:///mnt/new_volume/VS_code_base/moex_helper/src/foundry_client.py) | Подключение к `Data Foundry MCP` (`mcp.vrednyj-investor.ru/mcp`) для МСФО/РСБУ рядов внутри виджета Чёрной линии и вкладки разведки. |
| [src/magellan_gateway.py](file:///mnt/new_volume/VS_code_base/moex_helper/src/magellan_gateway.py) | Шлюз Magellan + MOEX: Order Flow, банки ЦБ (101/102, Н1.0), БПИФ, бондовый стресс-радар (`get_bonds_stress_radar`), валютные облигации `TQOD`/`TQOY` (`get_fx_debt_issuers`), ИПР сетей. |
| [src/tankermap_gateway.py](file:///mnt/new_volume/VS_code_base/moex_helper/src/tankermap_gateway.py) | Морская логистика экспорта (терминалы, DWT, Суэц, СПГ). |

---

## 2. Интеграции данных и кэширование

1. **`izi-invest.ru/mcp`**
   - **Портфели пользователя:** `47933` (`Ликвидная часть`, объединённый Альфа + ВТБ), `43431` (`Альфа`), `43436` (`Втб`), `43551` (`LOCK` — заблокированные FinEx, автоматически подмешиваются к `47933` в `get_portfolio_model`).
   - **Конфиг `get_izi_config()`:** возвращает `IziConfig(dict)` (поддерживает и `.get("token")`, и распаковку `url, token`). Приоритет: `st.secrets` / `os.environ` / дефолт.
   - **Журнал сделок и FIFO:** `fetch_portfolio_ledger(portfolio_id)` заказывает `blocks=["trades", "closed", "events", "reference"]` с `limit=2000` (и автодогрузкой по календарным годам `_paginate_block_by_years` при превышении) + дисковый кэш.
   - **Рыночный контекст:** `get_market_context` в MCP даёт актуальные `cbr_rate`, `fx.USD/EUR/CNY`, `imoex` — подключён в `fetch_market_context()` как резерв при сбое `cbr.ru` / MOEX ISS.

2. **Data Foundry MCP**
   - Стандартизированы: `fin.revenue`, `fin.operating_profit`, `fin.ebitda`, `fin.net_income`, `fin.cash_and_equivalents`, `fin.interest_bearing_debt`, `fin.total_equity`, `fin.total_assets`, `fin.capex`, банковские `bank.*`.
   - **Ограничение:** единой строки `fin.interest_expense` по всему рынку нет (только точечно в отдельных Databook вроде `afks.*`, `aflt.*`, `aqua.*`).

3. **Ускорение MOEX ISS и каскад цен**
   - В [streamlit_project.py](file:///mnt/new_volume/VS_code_base/moex_helper/streamlit_project.py) сначала читается `fundamentals_cache.csv`, и только для найденных тикеров (~44–62) вызывается `fetch_technical_indicators(..., max_workers=20)` без дублирующего `fetch_live_prices`.
   - Резерв вселенной тикеров: `data/moex_universe_cache.json` + `_build_static_fallback_universe()`; цены резервно берутся из `tech_data`, `my_portfolio` и `magellan_of`.

---

## 3. Инвестиционная логика: Скоринг и Чёрная линия

### Секторная классификация и особые группы
- **`STRUCTURAL_DISCOUNT_TICKERS`** (`SNGS`, `SNGSP`, `GAZP`, `FEES`, `UPRO`): отделены от `HOLDING_TICKERS` (`AFKS`, `SFIN`, `ENPG`).
  - Не получают `3.0 / P_BV` и бонус за закрытую от миноритариев кубышку.
  - В `Black Line`: для `SNGS` — `0.5 * (0.14 * BVPS) + 0.5 * DDM`; для `SNGSP` — уставной DDM + потолок `0.22 * BVPS`; для `GAZP`/`FEES`/`UPRO` — `0.14–0.20x BV` со штрафом за нулевые дивы / отриц. `FCF`.
- **`Value & Income` + `Income Reversion`**:
  - Штраф за нулевые дивиденды вне IT (`×0.55`, для чистых цикличных на дне цикла `×0.80`); низкие дивы `< 6%` прощаются только при подтверждённом `Income Reversion` (`FCF >= 12%` при `Debt/EBITDA <= 1.5` или `Rev_Growth >= 12%` и `ROE >= 15%`).
  - Для `ROSN` и др. нефтегаза с высоким `FCF` просадка спотового `P/E` компенсируется FCF-моделью (`req_fcf` привязан к `key_rate`), а в `management_filter` они проходят даже в режиме без портфеля.
- **Asset-light Потребсектор (`CONSUMER_TICKERS`)**:
  - Прибыльные (`BELU`, `MDMG`, `X5`): связка `P/E + DDM` без занижения балансовой формулой Грэма.
  - Убыточные / отрицательный FCF (`MGNT`): риск-дисконт `0.72 × P_market` (не экстраполирует старые дивиденды).
- **Штанга Талеба (`build_portfolio_rules`)**:
  - 0% длинных номинальных рублёвых ОФЗ («турецкий риск»); защитный резерв — валютный/золотой щит + фонд ликвидности.

### Учёт ключевой ставки, льготного и валютного долга
- **IT (`IT_TICKERS`), Цикличные, Золото, `UTILITIES_TICKERS` (`IRAO`, `HYDR` с коэф. `×0.65–0.75` за CAPEX/тарифы), `Income Reversion`:** все формулы Чёрной линии зависят от `key_rate`, а порог `Strong Buy` масштабируется (`12% + 0.75 * max(0, key_rate - 12)`).
- **Льготный / дешёвый долг (`_assess_debt_and_currency_profile`):** при `Debt/EBITDA > 1.2x` высокий `ROE >= key_rate` (с неотрицательным `FCF`) или дешёвые облигации (`bond_ytm <= key_rate + 1.5%`) отменяют повышенный ставочный дисконт; дорогой/стрессовый долг (`ROE < key_rate`, `FCF < 3%` или `YTM >= 22%`) усиливает дисконт пропорционально `key_rate`.
- **Валютная привязка долга:** на основе `TQOD`/`TQOY` + `FX_REVENUE_EXPORTERS` при ослаблении рубля (`USD >= 88`) экспортёры с рублёвым/хеджированным долгом получают мягкий плюс, а внутренние неэкспортёры с валютным долгом (`GAZP`, `SGZH`, `VKCO` и др.) — дисконт до `-20%` (и `×0.85` в `Health_Score`).

---

## 4. Важные правила эксплуатации и проверки

> [!IMPORTANT]
> **Streamlit Cloud Hot-Reload:** При `git pull` в запущенном процессе Cloud обновляет только главный файл страницы, оставляя `src/*` в `sys.modules`. Поэтому в начале [streamlit_project.py](file:///mnt/new_volume/VS_code_base/moex_helper/streamlit_project.py) и [4_💼_Реальный_Портфель_и_Сделки.py](file:///mnt/new_volume/VS_code_base/moex_helper/pages/4_%F0%9F%92%BC_%D0%A0%D0%B5%D0%B0%D0%BB%D1%8C%D0%BD%D1%8B%D0%B9_%D0%9F%D0%BE%D1%80%D1%82%D1%84%D0%B5%D0%BB%D1%8C_%D0%B8_%D0%A1%D0%B4%D0%B5%D0%BB%D0%BA%D0%B8.py) стоит `_ensure_fresh_module(...)` (сверяет `_LOADED_FILE_MTIME` модуля с диском). При добавлении новых параметров в функции `src/*` обязательно добавлять `_LOADED_FILE_MTIME = os.path.getmtime(__file__)` в модуль и вызов `_ensure_fresh_module`.

> [!WARNING]
> **Python и Git:** Запускать тесты только через `.venv/bin/python` (в системном `python3` нет `yfinance`/`streamlit`). В `.gitignore` заблокированы `*.json`, `*.csv`, `*.xlsx` (кроме whitelist-файлов), чтобы персональный дисковый кэш MCP и отчёты портфеля случайно не утекли в GitHub.

### Быстрая команда верификации перед коммитом
Сначала золотой тест Чёрной линии (замороженные входные данные, стандартный `unittest`, без зависимостей). Если он упал — формулы сдвинулись; при намеренной правке пересчитайте `GOLDEN` в [tests/test_black_line_golden.py](file:///mnt/new_volume/VS_code_base/moex_helper/tests/test_black_line_golden.py) и опишите в коммите, какие тикеры сдвинулись.
```bash
.venv/bin/python -m unittest discover -s tests -v
```
Колонка «Доверие модели» (`assess_model_consistency` в `src/black_line.py`) только помечает расхождения Health Score и Чёрной линии (апсайд > `UPSIDE_SANITY_CAP_PCT`=100%, сильный Health при MoS ≤ −25%, слабый Health при MoS ≥ 60%); расчёт и статусы не меняет.

```bash
.venv/bin/python -m py_compile streamlit_project.py fetch_fundamentals.py src/*.py pages/*.py && \
.venv/bin/python -c '
from streamlit.testing.v1 import AppTest
for p in ["streamlit_project.py", "pages/1_🎯_Мастер_подбора.py", "pages/4_💼_Реальный_Портфель_и_Сделки.py"]:
    at = AppTest.from_file(p, default_timeout=45).run()
    assert not at.exception, f"{p}: {at.exception}"
print("ALL_OK")
'
```
