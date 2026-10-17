import requests
import re
import json
import time
from pathlib import Path
import urllib3
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

# Списки позитивных и негативных слов для лексического анализа
POSITIVE_WORDS = [
    "лонг", "покупаю", "покупка", "ракета", "взлет", "рост", "отчет", 
    "дивиденды", "вверх", "хорошо", "докупаю", "плюс", "прибыль", "беру", 
    "дешево", "недооценен", "байбек"
]

NEGATIVE_WORDS = [
    "шорт", "продаю", "продажа", "дно", "слив", "падение", "ужас", 
    "плохо", "вниз", "режу", "лось", "кошмар", "коррекция", "минус", 
    "убыток", "дорого", "пузырь", "скам"
]

# Тикеры из портфеля пользователя (всегда включаются)
PORTFOLIO_TICKERS = [
    "MGNT", "SBER", "ROSN", "NMTP", "SVCB",
    "T", "SIBN", "BELU", "CHMF", "NLMK",
    "SNGS", "TRNFP", "GAZP"
]

# Резервный список (все основные ликвидные компании MOEX)
FALLBACK_TICKERS = [
    "SBER", "SBERP", "LKOH", "GAZP", "ROSN", "NVTK", "YDEX", "YNDX", "T", "TCSG",
    "PLZL", "MGNT", "CHMF", "NLMK", "SNGS", "SNGSP", "MTSS", "TATN", "TATNP", "TRNFP",
    "SVCB", "HEAD", "ASTR", "DIAS", "DATA", "POSI", "OZON", "MOEX", "AFKS",
    "FLOT", "ALRS", "BANE", "BANEP", "RNFT", "SOFL", "VKCO", "MAGN", "PIKK",
    "CNRU", "CIAN", "BELU", "BSPB", "DOMRF", "ENPG", "FEES", "IVAT", "MDMG",
    "MTLR", "NMTP", "OZPH", "PHOR", "PRMD", "RAGR", "RENI", "RTKM", "RUAL",
    "SELG", "SFIN", "SGZH", "SIBN", "SMLT", "TRMK", "UGLD", "UGC", "UPRO",
    "VTBR", "WUSH", "X5", "AQUA", "HYDR", "IRAO", "CBOM", "AFLT"
]

COMPANY_NAMES = {
    "SBER": "Сбербанк",
    "SBERP": "Сбербанк (преф)",
    "GAZP": "Газпром",
    "LKOH": "ЛУКОЙЛ",
    "ROSN": "Роснефть",
    "NVTK": "НОВАТЭК",
    "GMKN": "ГМК Норильский никель",
    "YDEX": "Яндекс",
    "YNDX": "Яндекс",
    "T": "Т-Банк",
    "TCSG": "Т-Банк (ТКС Холдинг)",
    "PLZL": "Полюс Золото",
    "MGNT": "Магнит",
    "CHMF": "Северсталь",
    "NLMK": "НЛМК",
    "MAGN": "ММК",
    "VTBR": "ВТБ",
    "TATN": "Татнефть",
    "TATNP": "Татнефть (преф)",
    "SNGS": "Сургутнефтегаз",
    "SNGSP": "Сургутнефтегаз (преф)",
    "ALRS": "АЛРОСА",
    "MOEX": "Московская Биржа",
    "AFKS": "АФК Система",
    "OZON": "Озон",
    "MTSS": "МТС",
    "IRAO": "Интер РАО",
    "FLOT": "Совкомфлот",
    "CBOM": "МКБ",
    "AFLT": "Аэрофлот",
    "TRNFP": "Транснефть (преф)",
    "SVCB": "Совкомбанк",
    "HEAD": "Хэдхантер",
    "POSI": "Группа Позитив",
    "ASTR": "Группа Астра",
    "DIAS": "Диасофт",
    "DATA": "Аренадата",
    "SOFL": "Софтлайн",
    "VKCO": "ВК (VK)",
    "PIKK": "ПИК",
    "SMLT": "Самолёт",
    "EUTR": "ЕвроТранс",
    "BELU": "НоваБев Групп (Белуга)",
    "BSPB": "Банк Санкт-Петербург",
    "CNRU": "Циан",
    "CIAN": "Циан",
    "DOMRF": "Дом.РФ",
    "ENPG": "Эн+ Груп",
    "FEES": "ФСК-Россети",
    "IVAT": "Ива (IVA Technologies)",
    "MDMG": "Мать и дитя",
    "MTLR": "Мечел",
    "NMTP": "НМТП",
    "OZPH": "Озон Фармацевтика",
    "PHOR": "ФосАгро",
    "PRMD": "Промомед",
    "RAGR": "Русагро",
    "RENI": "Ренессанс Страхование",
    "RNFT": "РуссНефть",
    "RTKM": "Ростелеком",
    "RUAL": "РУСАЛ",
    "SELG": "Селигдар",
    "SFIN": "ЭсЭфАй (SFI)",
    "SGZH": "Сегежа Групп",
    "SIBN": "Газпром нефть",
    "TRMK": "ТМК",
    "UGLD": "ЮГК (Южуралзолото)",
    "UGC": "Южуралзолото",
    "UPRO": "Юнипро",
    "WUSH": "Whoosh (Вуш)",
    "X5": "X5 Group (ИКС 5)",
    "FIVE": "X5 Group",
    "AQUA": "Инарктика",
    "BANE": "Башнефть",
    "BANEP": "Башнефть (преф)",
    "HYDR": "РусГидро",
    "MSNG": "Мосэнерго",
    "LSNG": "Ленэнерго",
    "LSNGP": "Ленэнерго (преф)",
    "RASP": "Распадская",
    "QIWI": "Киви (QIWI)"
}

TICKER_ALIASES = {
    'CIAN': 'CNRU',
    'ЦИАН': 'CNRU',
    'YNDX': 'YDEX',
    'ЯНДЕКС': 'YDEX',
    'TCSG': 'T',
    'Т-БАНК': 'T',
    'ТБАНК': 'T',
    'ТИНЬКОФФ': 'T',
    'ТКС': 'T',
    'UGC': 'UGLD',
    'ЮГК': 'UGLD',
    'ЮЖУРАЛЗОЛОТО': 'UGLD',
    'FIVE': 'X5',
    'ПЯТЕРОЧКА': 'X5',
    'ИКС5': 'X5',
    'NOVA': 'BELU',
    'БЕЛУГА': 'BELU',
    'НОВАБЕВ': 'BELU',
    'СБЕР': 'SBER',
    'СБЕРБАНК': 'SBER',
    'ЛУКОЙЛ': 'LKOH',
    'ГАЗПРОМ': 'GAZP',
    'РОСНЕФТЬ': 'ROSN',
    'НОВАТЭК': 'NVTK',
    'НОРНИКЕЛЬ': 'GMKN',
    'САМОЛЕТ': 'SMLT',
    'МАГНИТ': 'MGNT',
    'ФОСАГРО': 'PHOR',
    'РУСАЛ': 'RUAL',
    'СЕВЕРСТАЛЬ': 'CHMF',
    'НЛМК': 'NLMK',
    'ММК': 'MAGN',
    'ПОЛЮС': 'PLZL',
    'ТАТНЕФТЬ': 'TATN',
    'СУРГУТ': 'SNGS',
    'АЛРОСА': 'ALRS',
    'АЭРОФЛОТ': 'AFLT',
    'ОЗОН': 'OZON',
    'МТС': 'MTSS',
    'ВТБ': 'VTBR',
    'СОВКОМБАНК': 'SVCB',
    'ХЭДХАНТЕР': 'HEAD',
    'ПОЗИТИВ': 'POSI',
    'АСТРА': 'ASTR',
    'ДИАСОФТ': 'DIAS',
    'СОВКОМФЛОТ': 'FLOT',
    'НМТП': 'NMTP',
    'МЕЧЕЛ': 'MTLR',
    'РОСТЕЛЕКОМ': 'RTKM',
    'СЕГЕЖА': 'SGZH',
    'ВУШ': 'WUSH',
    'WHOOSH': 'WUSH',
    'ТМК': 'TRMK',
    'РУССНЕФТЬ': 'RNFT',
    'ИНТЕР РАО': 'IRAO',
    'РУСГИДРО': 'HYDR',
    'ЮНИПРО': 'UPRO',
    'ДОМРФ': 'DOMRF',
    'ДОМ.РФ': 'DOMRF',
    'ИВА': 'IVAT',
    'ПРОМОМЕД': 'PRMD',
    'МАТЬ И ДИТЯ': 'MDMG'
}

SMARTLAB_FORUM_MAP = {
    'CIAN': 'CNRU',
    'YNDX': 'YDEX',
    'TCSG': 'T',
    'FIVE': 'X5',
    'UGC': 'UGLD',
    'NOVA': 'BELU'
}

PULSE_ALIASES = {
    'CNRU': ['CIAN'],
    'CIAN': ['CNRU'],
    'YDEX': ['YNDX'],
    'YNDX': ['YDEX'],
    'T': ['TCSG'],
    'TCSG': ['T'],
    'X5': ['FIVE'],
    'FIVE': ['X5'],
    'UGLD': ['UGC'],
    'UGC': ['UGLD'],
    'BELU': ['NOVA']
}

def resolve_ticker(raw_ticker: str) -> str:
    """Нормализует введенный тикер или название компании к официальному тикеру MOEX."""
    if not raw_ticker:
        return ""
    cleaned = str(raw_ticker).strip().upper()
    return TICKER_ALIASES.get(cleaned, cleaned)

MIN_DAILY_TURNOVER_RUB = 50_000_000
MOEX_TQBR_URL = "https://iss.moex.com/iss/engines/stock/markets/shares/boards/TQBR/securities.json"

def fetch_moex_tickers():
    """Динамически получает список ликвидных тикеров с MOEX ISS API."""
    try:
        params = {
            "iss.meta": "off",
            "iss.only": "securities,marketdata",
            "securities.columns": "SECID,LISTLEVEL",
            "marketdata.columns": "SECID,VALTODAY",
        }
        response = requests.get(MOEX_TQBR_URL, params=params, timeout=30)
        response.raise_for_status()
        data = response.json()

        turnover_by_ticker = {
            row[0]: row[1] or 0
            for row in data["marketdata"]["data"]
        }
        
        max_turnover = max(turnover_by_ticker.values()) if turnover_by_ticker else 0
        market_is_open = max_turnover > MIN_DAILY_TURNOVER_RUB

        tickers = set()
        for ticker, list_level in data["securities"]["data"]:
            if list_level not in (1, 2) and ticker not in PORTFOLIO_TICKERS:
                continue
            turnover_rub = turnover_by_ticker.get(ticker, 0)
            if market_is_open and turnover_rub < MIN_DAILY_TURNOVER_RUB and ticker not in PORTFOLIO_TICKERS:
                continue
            tickers.add(ticker)
        
        # Всегда добавляем тикеры из портфеля
        tickers.update(PORTFOLIO_TICKERS)
        
        print(f"Fetched {len(tickers)} tickers from MOEX API")
        return sorted(tickers)
        
    except Exception as e:
        print(f"Failed to fetch MOEX tickers: {e}. Using fallback list.")
        return sorted(set(FALLBACK_TICKERS + PORTFOLIO_TICKERS))

def get_all_supported_tickers():
    """Возвращает полный отсортированный список всех поддерживаемых тикеров без дублей и технических фондов."""
    base_set = set(FALLBACK_TICKERS + PORTFOLIO_TICKERS)
    try:
        moex = fetch_moex_tickers()
        base_set.update(moex)
    except Exception:
        pass
    try:
        cache_path = Path(__file__).parent / "fundamentals_cache.csv"
        if cache_path.exists():
            import pandas as pd
            df_c = pd.read_csv(cache_path)
            base_set.update(df_c['ticker'].dropna().unique().tolist())
    except Exception:
        pass
    # Исключаем технические БПИФы денежного рынка
    skip_prefixes = ("AKM", "AKF", "AMF", "AMN", "BCS", "FIX", "SBMM", "LQDT")
    filtered = [t for t in base_set if not t.startswith(skip_prefixes)]
    return sorted(set(filtered))

ANALYTICS_WORDS = [
    "отчет", "выручка", "прибыль", "дивиденд", "дивы", "ставка", "цб", "таргет",
    "байбек", "купон", "маржа", "ebitda", "долг", "сопротивлени", "поддержк",
    "уровен", "капитализаци", "мультипликатор", "прогноз", "мсфо", "рсбу"
]

OUTPUT_FILE = Path(__file__).parent / "sentiment.json"

def clean_html(raw_html):
    cleanr = re.compile('<.*?>')
    return re.sub(cleanr, ' ', raw_html).lower()

def analyze_sentiment(text):
    pos_count = sum(1 for word in POSITIVE_WORDS if re.search(r'\b' + word + r'[а-я]*\b', text))
    neg_count = sum(1 for word in NEGATIVE_WORDS if re.search(r'\b' + word + r'[а-я]*\b', text))
    
    return pos_count, neg_count

def fetch_forum_sentiment(ticker, max_age_days=30):
    url = f"https://smart-lab.ru/forum/{ticker}"
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36"
    }
    
    try:
        response = requests.get(url, headers=headers, timeout=10)
        if response.status_code != 200:
            return None
            
        from bs4 import BeautifulSoup
        import datetime
        soup = BeautifulSoup(response.text, 'html.parser')
        items = soup.select('li.cm_wrap, div.post')
        if not items:
            items = soup.select('div.comment_body, div.text')

        if not items:
            return {
                "score": 0.0,
                "pos_words": 0,
                "neg_words": 0,
                "posts_analyzed": 0,
                "has_recent_posts": False,
                "message": "Нет сообщений за последний месяц",
                "timestamp": time.time()
            }

        cutoff = datetime.datetime.now() - datetime.timedelta(days=max_age_days)
        total_pos = 0
        total_neg = 0
        recent_posts_count = 0

        for it in items[:30]:
            time_tag = it.select_one('time, .time, .date')
            time_str = ""
            if time_tag:
                time_str = time_tag.get('datetime') or time_tag.get_text(strip=True)
            
            dt = parse_time_to_dt(time_str)
            # Отсекаем сообщения старше 30 дней от запроса
            if dt != datetime.datetime.min and dt < cutoff:
                continue

            text_tag = it.select_one('.text') or it.select_one('.comment_body') or it
            clean_text = clean_html(text_tag.get_text(separator=' ', strip=True))
            if len(clean_text) < 15:
                continue

            p, n = analyze_sentiment(clean_text)
            total_pos += p
            total_neg += n
            recent_posts_count += 1

        if recent_posts_count == 0:
            return {
                "score": 0.0,
                "pos_words": 0,
                "neg_words": 0,
                "posts_analyzed": 0,
                "has_recent_posts": False,
                "message": "Нет сообщений за последний месяц",
                "timestamp": time.time()
            }

        score = (total_pos - total_neg) / (total_pos + total_neg + 1)
        return {
            "score": round(score, 2),
            "pos_words": total_pos,
            "neg_words": total_neg,
            "posts_analyzed": recent_posts_count,
            "has_recent_posts": True,
            "timestamp": time.time()
        }
    except Exception as e:
        print(f"Error fetching {ticker}: {e}")
        return None

def extract_meaningful_messages(ticker, max_pages=2, max_messages=50, max_age_days=30):
    from bs4 import BeautifulSoup
    import datetime
    
    resolved = resolve_ticker(ticker)
    forum_ticker = SMARTLAB_FORUM_MAP.get(resolved, resolved)
    messages = []
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
    }
    cutoff = datetime.datetime.now() - datetime.timedelta(days=max_age_days) if max_age_days else None
    
    for page in range(1, max_pages + 1):
        if page == 1:
            url = f"https://smart-lab.ru/forum/{forum_ticker}"
        else:
            url = f"https://smart-lab.ru/forum/{forum_ticker}/page{page}/"
            
        try:
            r = requests.get(url, headers=headers, timeout=10)
            if r.status_code != 200:
                break
                
            soup = BeautifulSoup(r.text, 'html.parser')
            # Ищем все контейнеры постов
            items = soup.select('li.cm_wrap, div.post')
            if not items:
                # Fallback для других вариантов
                items = soup.select('div.comment_body, div.text')
                
            for it in items:
                # Для li.cm_wrap и подобных
                text_tag = it.select_one('.text') or (it if 'text' in it.get('class', []) else None)
                if not text_tag:
                    text_tag = it.select_one('.comment_body')
                if not text_tag:
                    continue
                    
                raw_text = text_tag.get_text(separator=' ', strip=True)
                if len(raw_text) < 30: # Слишком коротко
                    continue
                    
                # Получаем автора
                author_tag = it.select_one('a[href*="/profile/"], a[href*="/my/"], .user_name, .author, .name')
                author = (author_tag.get_text(strip=True) if author_tag else "").strip() or "Инвестор"
                
                # Получаем время
                time_tag = it.select_one('time, .time, .date')
                time_str = ""
                if time_tag:
                    time_str = time_tag.get('datetime') or time_tag.get_text(strip=True)
                
                dt = parse_time_to_dt(time_str)
                # Отсекаем сообщения старше месяца (max_age_days) от момента запроса
                if cutoff and dt != datetime.datetime.min:
                    if dt < cutoff:
                        continue

                display_time = dt.strftime("%Y-%m-%d %H:%M") if dt != datetime.datetime.min else time_str
                    
                # Получаем ссылку на коммент
                data_id = it.get('data-id')
                link = f"https://smart-lab.ru/forum/{ticker}#comment{data_id}" if data_id else url
                
                # Анализ текста
                clean_txt = clean_html(str(text_tag))
                p, n = analyze_sentiment(clean_txt)
                
                # Ищем аналитику
                a_count = sum(1 for word in ANALYTICS_WORDS if re.search(r'\b' + word + r'[а-я]*\b', clean_txt))
                
                # Фильтруем откровенный спам: если нет ни позитива, ни негатива, ни аналитики и текст короткий
                if p == 0 and n == 0 and a_count == 0 and len(raw_text) < 10:
                    continue
                
                if p > n: trend = "positive"
                elif n > p: trend = "negative"
                elif a_count > 0: trend = "analytics"
                else: trend = "neutral"
                
                messages.append({
                    "source": "Smart-Lab",
                    "author": author,
                    "time": display_time,
                    "dt": dt,
                    "text": raw_text,
                    "link": link,
                    "pos": p,
                    "neg": n,
                    "analytics": a_count,
                    "trend": trend
                })
                
                if len(messages) >= max_messages:
                    return messages
                    
        except Exception as e:
            print(f"Error fetching detailed {ticker} page {page}: {e}")
            break
            
        time.sleep(0.5) # Пауза между страницами
        
    return messages

def extract_pulse_messages(ticker, max_messages=50, max_age_days=30):
    import datetime
    resolved = resolve_ticker(ticker)
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
        "Accept": "application/json"
    }
    cutoff = datetime.datetime.now() - datetime.timedelta(days=max_age_days) if max_age_days else None
    
    tickers_to_query = [resolved]
    for alt in PULSE_ALIASES.get(resolved, []):
        if alt not in tickers_to_query:
            tickers_to_query.append(alt)

    messages = []
    seen_ids = set()
    seen_texts = set()

    for current_t in tickers_to_query:
        if len(messages) >= max_messages:
            break
        limit_needed = max_messages - len(messages)
        url = f"https://www.tbank.ru/api/invest-gw/social/v1/post/instrument/{current_t}?limit={limit_needed}"
        try:
            # Т-Банк использует российский корневой сертификат Минцифры, поэтому отключаем SSL-проверку для предотвращения SSLCertVerificationError
            r = requests.get(url, headers=headers, timeout=10, verify=False)
            if r.status_code != 200:
                continue
                
            data = r.json()
            items = data.get("payload", {}).get("items", [])
            
            for item in items:
                post_id = item.get("id", "")
                if post_id and post_id in seen_ids:
                    continue
                if post_id:
                    seen_ids.add(post_id)

                raw_text = item.get("content", {}).get("text", "") or item.get("text", "")
                if not raw_text or len(raw_text) < 15:
                    continue
                    
                snippet = raw_text[:60]
                if snippet in seen_texts:
                    continue
                seen_texts.add(snippet)

                author = item.get("nickname") or item.get("owner", {}).get("nickname", "Аноним")
                
                # Парсинг времени (формат: 2026-09-02T11:14:03.794Z)
                time_str = item.get("inserted", "")
                dt = parse_time_to_dt(time_str)
                # Отсекаем сообщения старше месяца (max_age_days) от момента запроса
                if cutoff and dt != datetime.datetime.min:
                    if dt < cutoff:
                        continue

                display_time = dt.strftime("%Y-%m-%d %H:%M") if dt != datetime.datetime.min else time_str
                link = f"https://www.tbank.ru/invest/social/profile/{author}/{post_id}/" if author != "Аноним" and post_id else url
                
                clean_txt = clean_html(raw_text)
                p, n = analyze_sentiment(clean_txt)
                a_count = sum(1 for word in ANALYTICS_WORDS if re.search(r'\b' + word + r'[а-я]*\b', clean_txt))
                
                if p == 0 and n == 0 and a_count == 0 and len(raw_text) < 10:
                    continue
                    
                if p > n: trend = "positive"
                elif n > p: trend = "negative"
                elif a_count > 0: trend = "analytics"
                else: trend = "neutral"
                
                messages.append({
                    "source": "Пульс",
                    "author": author,
                    "time": display_time,
                    "dt": dt,
                    "text": raw_text,
                    "link": link,
                    "pos": p,
                    "neg": n,
                    "analytics": a_count,
                    "trend": trend
                })
                if len(messages) >= max_messages:
                    break
        except Exception as e:
            print(f"Error fetching Pulse detailed {current_t}: {e}")
            
    return messages



RU_MONTHS = {
    'янв': 1, 'фев': 2, 'мар': 3, 'апр': 4, 'май': 5, 'мая': 5, 'июн': 6,
    'июл': 7, 'авг': 8, 'сен': 9, 'окт': 10, 'ноя': 11, 'дек': 12
}


def parse_time_to_dt(time_str: str):
    """
    Преобразует различные форматы дат из Пульса и Smart-Lab в объект datetime
    для фильтрации по периоду от момента запроса и корректной сортировки.
    """
    import datetime
    if not time_str:
        return datetime.datetime.min
    now = datetime.datetime.now()
    raw = str(time_str).strip()
    s = raw.lower()

    # 1. ISO-8601 формат (Smart-Lab datetime атрибут или inserted из Пульса)
    try:
        iso_s = raw.replace('Z', '+00:00')
        dt = datetime.datetime.fromisoformat(iso_s)
        if dt.tzinfo is not None:
            dt = dt.replace(tzinfo=None)
        return dt
    except Exception:
        pass

    try:
        # 2. Относительное время: "X минут/часов/дней назад"
        rel_m = re.search(r'(\d+)\s*(мин|час|дн|сек)', s)
        if rel_m and 'назад' in s:
            num = int(rel_m.group(1))
            unit = rel_m.group(2)
            if 'сек' in unit:
                return now - datetime.timedelta(seconds=num)
            elif 'мин' in unit:
                return now - datetime.timedelta(minutes=num)
            elif 'час' in unit:
                return now - datetime.timedelta(hours=num)
            elif 'дн' in unit:
                return now - datetime.timedelta(days=num)

        # 3. "сегодня, 14:20" / "вчера, 22:15"
        if 'сегодня' in s:
            parts = s.split(',')
            if len(parts) > 1:
                t = parts[1].strip()
                h, m = map(int, t.split(':')[:2])
                return now.replace(hour=h, minute=m, second=0, microsecond=0)
            return now
        elif 'вчера' in s:
            parts = s.split(',')
            yest = now - datetime.timedelta(days=1)
            if len(parts) > 1:
                t = parts[1].strip()
                h, m = map(int, t.split(':')[:2])
                return yest.replace(hour=h, minute=m, second=0, microsecond=0)
            return yest

        # 4. "YYYY-MM-DD HH:MM"
        if re.match(r'^\d{4}-\d{2}-\d{2}', s):
            return datetime.datetime.strptime(s[:16], '%Y-%m-%d %H:%M')

        # 5. "DD.MM.YYYY HH:MM" или "DD.MM.YY"
        dot_m = re.search(r'(\d{1,2})\.(\d{1,2})\.(\d{2,4})(?:[ ,]+(\d{1,2}):(\d{2}))?', s)
        if dot_m:
            day = int(dot_m.group(1))
            month = int(dot_m.group(2))
            yr = int(dot_m.group(3))
            year = yr if yr > 100 else 2000 + yr
            hour = int(dot_m.group(4)) if dot_m.group(4) else 0
            minute = int(dot_m.group(5)) if dot_m.group(5) else 0
            return datetime.datetime(year, month, day, hour, minute)

        # 6. Текстовые даты Smart-Lab: "15 октября 2026 10:30" или "15 окт, 10:30"
        m = re.search(r'(\d{1,2})\s+([а-я]{3,8})(?:\s+(\d{4}))?.*?(\d{1,2}):(\d{2})', s)
        if m:
            day = int(m.group(1))
            mon_str = m.group(2)[:3]
            month = RU_MONTHS.get(mon_str, now.month)
            year = int(m.group(3)) if m.group(3) else now.year
            hour = int(m.group(4))
            minute = int(m.group(5))
            return datetime.datetime(year, month, day, hour, minute)
    except Exception:
        pass
    return datetime.datetime.min


def filter_messages_by_date(messages: list, max_age_days: int = 30) -> list:
    """
    Оставляет только сообщения за последние max_age_days (по умолчанию 30 дней от момента запроса).
    """
    if not messages:
        return []
    import datetime
    cutoff = datetime.datetime.now() - datetime.timedelta(days=max_age_days)
    result = []
    for m in messages:
        dt = m.get("dt") or parse_time_to_dt(m.get("time", ""))
        if dt != datetime.datetime.min and dt >= cutoff:
            result.append(m)
    return result


def extract_aggregated_messages(ticker, max_messages=50, max_age_days=30):
    """
    Одновременно агрегирует обсуждения из Т-Банк Пульс и Smart-Lab,
    ограничивая выборку последними max_age_days (30 дней от момента запроса),
    объединяет их и возвращает единую ленту сообщений.
    """
    from concurrent.futures import ThreadPoolExecutor
    limit_per_source = max(15, max_messages // 2 + 5)

    with ThreadPoolExecutor(max_workers=2) as executor:
        f_pulse = executor.submit(extract_pulse_messages, ticker, limit_per_source, max_age_days)
        f_smart = executor.submit(extract_meaningful_messages, ticker, 2, limit_per_source, max_age_days)
        pulse_msgs = f_pulse.result() or []
        smart_msgs = f_smart.result() or []

    combined = pulse_msgs + smart_msgs
    if max_age_days:
        combined = filter_messages_by_date(combined, max_age_days=max_age_days)
    combined.sort(key=lambda m: parse_time_to_dt(m.get("time", "")), reverse=True)
    return combined[:max_messages]


TICKER_SYNONYMS = {
    'SBER': ['сбер', 'sber', 'греф', 'сбербанк'],
    'SBERP': ['сбер', 'sber', 'греф', 'сбербанк', 'сберпреф'],
    'GAZP': ['газпром', 'gazp', 'миллер'],
    'LKOH': ['лукойл', 'lkoh', 'алекперов'],
    'ROSN': ['роснефть', 'rosn', 'сечин'],
    'NVTK': ['новатэк', 'nvtk', 'михельсон'],
    'GMKN': ['норникель', 'гмк', 'gmkn', 'потанин'],
    'YDEX': ['яндекс', 'ydex', 'yndx'],
    'YNDX': ['яндекс', 'ydex', 'yndx'],
    'T': ['т-банк', 'тбанк', 'тинькофф', 'ткс', 'tcsg'],
    'TCSG': ['т-банк', 'тбанк', 'тинькофф', 'ткс', 'tcsg'],
    'MGNT': ['магнит', 'mgnt'],
    'PLZL': ['полюс', 'plzl', 'золот'],
    'CHMF': ['северсталь', 'chmf', 'мордашов'],
    'NLMK': ['нлмк', 'nlmk', 'лисин'],
    'MAGN': ['ммк', 'magn', 'рашников'],
    'VTBR': ['втб', 'vtbr', 'костин'],
    'TATN': ['татнефть', 'tatn'],
    'TATNP': ['татнефть', 'tatn', 'татнефтьпреф'],
    'SNGS': ['сургут', 'sngs', 'богданов', 'сургутнефтегаз'],
    'SNGSP': ['сургут', 'sngs', 'богданов', 'сургутнефтегаз', 'преф'],
    'ALRS': ['алроса', 'alrs', 'алмаз'],
    'MOEX': ['мосбирж', 'moex'],
    'AFKS': ['система', 'afks', 'евтушенков'],
    'OZON': ['озон', 'ozon'],
    'MTSS': ['мтс', 'mtss'],
    'IRAO': ['интер рао', 'irao'],
    'FLOT': ['совкомфлот', 'flot'],
    'CBOM': ['мкб', 'cbom'],
    'AFLT': ['аэрофлот', 'aflt'],
    'TRNFP': ['транснефть', 'trnfp', 'токарев'],
    'SVCB': ['совкомбанк', 'svcb'],
    'HEAD': ['хэдхантер', 'hh', 'head'],
    'POSI': ['позитив', 'posi'],
    'ASTR': ['астра', 'astr'],
    'DIAS': ['диасофт', 'dias'],
    'DATA': ['аренадата', 'data'],
    'SOFL': ['софтлайн', 'sofl'],
    'VKCO': ['вк', 'vkco', 'вконтакте'],
    'PIKK': ['пик', 'pikk'],
    'SMLT': ['самолет', 'smlt'],
    'EUTR': ['евротранс', 'eutr', 'трасса'],
    'BELU': ['белуг', 'новабев', 'belu', 'novabev'],
    'BSPB': ['бспб', 'bspb', 'банк спб', 'санкт-петербург'],
    'CNRU': ['циан', 'cian', 'cnru', 'циана', 'циану', 'cian.ru', 'cyan'],
    'CIAN': ['циан', 'cian', 'cnru', 'циана', 'циану', 'cian.ru', 'cyan'],
    'DOMRF': ['домрф', 'дом.рф', 'domrf', 'дом рф'],
    'ENPG': ['эн+', 'enpg', 'эн плюс', 'en+'],
    'FEES': ['россети', 'fees', 'фск', 'фск-россети'],
    'IVAT': ['ива', 'ivat', 'iva'],
    'MDMG': ['мать и дитя', 'mdmg', 'курцер', 'мд медикал'],
    'MTLR': ['мечел', 'mtlr', 'зюзин'],
    'NMTP': ['нмтп', 'nmtp', 'новороссийск'],
    'OZPH': ['озон фарма', 'ozph', 'озон фармацевтика'],
    'PHOR': ['фосагро', 'phor', 'гурьев'],
    'PRMD': ['промомед', 'prmd'],
    'RAGR': ['русагро', 'ragr', 'мошкович'],
    'RENI': ['ренессанс', 'reni'],
    'RNFT': ['русснефть', 'rnft', 'гуцериев'],
    'RTKM': ['ростелеком', 'rtkm', 'осеевский'],
    'RUAL': ['русал', 'rual', 'дерипаск'],
    'SELG': ['селигдар', 'selg'],
    'SFIN': ['эсэфай', 'sfin', 'сфи'],
    'SGZH': ['сегежа', 'sgzh', 'шамолин'],
    'SIBN': ['газпром нефть', 'газпромнефть', 'sibn', 'дюков'],
    'TRMK': ['тмк', 'trmk', 'пумпянский'],
    'UGLD': ['югк', 'ugld', 'ugc', 'струков', 'южуралзолото'],
    'UGC': ['югк', 'ugld', 'ugc', 'струков', 'южуралзолото'],
    'UPRO': ['юнипро', 'upro'],
    'WUSH': ['вуш', 'whoosh', 'wush'],
    'X5': ['х5', 'x5', 'пятерочк', 'перекресток', 'five'],
    'FIVE': ['х5', 'x5', 'пятерочк', 'перекресток', 'five'],
    'AQUA': ['инарктик', 'aqua', 'русская аквакультура'],
    'BANE': ['башнефть', 'bane'],
    'BANEP': ['башнефть', 'banep'],
    'HYDR': ['русгидро', 'hydr'],
    'QIWI': ['киви', 'qiwi']
}


def get_ticker_keywords(ticker: str) -> list:
    """Возвращает список синонимов, названий компании и тикеров для фильтрации."""
    raw = str(ticker).strip().upper()
    resolved = resolve_ticker(raw)
    kws = set()
    for t in [raw, resolved]:
        if t:
            kws.update(TICKER_SYNONYMS.get(t, []))
            kws.add(t.lower())
            kws.add(f"${t.lower()}")
    for alt in PULSE_ALIASES.get(resolved, []):
        kws.update(TICKER_SYNONYMS.get(alt, []))
        kws.add(alt.lower())
        kws.add(f"${alt.lower()}")
    return list(kws)


def filter_relevant_messages(messages: list, ticker: str) -> list:
    """
    Отсеивает сообщения новостных ботов и агрегаторов, где тикер упомянут только
    в списке 10+ других хештегов, но в самом тексте о компании ничего нет.
    """
    if not ticker or not messages:
        return messages
    keywords = get_ticker_keywords(ticker)
    filtered = []
    for m in messages:
        text_lower = m.get("text", "").lower()
        source = m.get("source", "")
        # Если форум Smart-Lab по тикеру, то ветка целевая
        if source == "Smart-Lab":
            filtered.append(m)
            continue
        # Для Пульса проверяем прямое упоминание в тексте
        if any(k in text_lower for k in keywords):
            filtered.append(m)
    return filtered if filtered else messages


def generate_structured_summary(messages: list, ticker: str = "") -> dict:
    """
    Умный экстрактивный суммаризатор, ориентированный строго на целевой тикер.
    Анализирует сообщения и формирует тезисы по 3 категориям:
    - 🟢 Драйверы роста (бычий тезис)
    - 🔴 Риски и негатив (медвежий тезис)
    - 📊 Факты, отчеты и дивиденды
    Отсеивает оффтоп, спам-ботов, чужие тикеры и макро-сводки.
    """
    pos_items = []
    neg_items = []
    an_items = []
    seen = set()

    ticker_clean = ticker.strip().upper() if ticker else ""
    keywords = get_ticker_keywords(ticker_clean) if ticker_clean else []

    for m in messages:
        raw = m.get("text", "")
        source = m.get("source", "")
        author = m.get("author", "")

        parts = [p.strip() for p in re.split(r"(?<=[.!?\n])\s+", raw) if 30 <= len(p.strip()) <= 260]
        for p in parts:
            p_clean = re.sub(r"[\s\n]+", " ", p).strip()
            p_lower = p_clean.lower()

            # Фильтр спама ссылок, хэштегов и перечислений тикеров
            if "http" in p_lower or "t.me" in p_lower or "[&" in p_clean:
                continue
            if p_clean.count("#") >= 2:
                continue
            tags = re.findall(r"\{\$[A-Za-z0-9_]+\}", p_clean)
            if len(tags) >= 2:
                continue
            words = re.findall(r"[а-яА-Яa-zA-Z]{3,}", p_clean)
            if len(words) < 5:
                continue

            # Проверка релевантности целевому эмитенту
            if ticker_clean:
                has_target = any(k in p_lower for k in keywords)
                foreign_tags = [t.upper() for t in re.findall(r"\{\$([A-Za-z0-9_]+)\}", p_clean) if t.upper() != ticker_clean]
                if foreign_tags and not has_target:
                    continue
                # Для постов из Пульса требуем явного упоминания компании
                if source == "Пульс" and not has_target:
                    continue

            norm = p_lower[:50]
            if norm in seen:
                continue
            seen.add(norm)

            has_pos = any(re.search(r"\b" + w + r"[а-я]*\b", p_lower) for w in POSITIVE_WORDS)
            has_neg = any(re.search(r"\b" + w + r"[а-я]*\b", p_lower) for w in NEGATIVE_WORDS)
            has_an = any(re.search(r"\b" + w + r"[а-я]*\b", p_lower) for w in ANALYTICS_WORDS) or bool(
                re.search(r"\d+[\s,]?\d*\s*(?:млрд|трлн|млн|руб|₽|%)", p_lower)
            )

            src = f"[{source}] {author}"
            formatted = f"{p_clean} *({src})*"

            if has_pos and not has_neg and len(pos_items) < 3:
                pos_items.append(formatted)
            elif has_neg and not has_pos and len(neg_items) < 3:
                neg_items.append(formatted)
            elif has_an and len(an_items) < 3:
                an_items.append(formatted)

    return {
        "pos": pos_items,
        "neg": neg_items,
        "an": an_items
    }


# =====================================================================
# КОНФИГУРАЦИЯ НЕЙРОСЕТЕЙ (OPENROUTER AI)
# =====================================================================
# Модель по умолчанию (только бесплатные варианты)
DEFAULT_OPENROUTER_MODEL = "liquid/lfm-2.5-2.6b:free"

# Максимальное количество токенов на ответ модели (до 3000 токенов для развернутых статей)
MAX_SUMMARY_TOKENS = 3000

# Список поддерживаемых бесплатных моделей OpenRouter (100% Free, $0.00 / 0 токенов)
OPENROUTER_FREE_MODELS = [
    "liquid/lfm-2.5-2.6b:free",           # 💧 LiquidAI LFM 2.5 (быстрая, стабильная, без очередей)
    "openrouter/free",                    # 🔄 Автовыбор свободной бесплатной модели
    "dots-studio/dots-3-note-preview:free", # 📝 Dots Studio 3-Note Preview
    "apodex/apodex-1.1-mini:free",        # ⚡ Apodex 1.1 Mini
    "google/gemma-4-31b-it:free",         # 🧠 Google Gemma 4 31B (DeepMind)
    "google/gemma-4-26b-a4b-it:free",     # ⚡ Google Gemma 4 26B
    "nvidia/nemotron-3.5-lightning:free", # 🚀 NVIDIA Nemotron 3.5 Lightning
]


def summarize_with_openrouter(messages: list, ticker: str = "", api_key: str = None, model: str = None) -> dict:
    """
    Генерирует связную аналитическую выжимку через OpenRouter API.
    ГАРАНТИЯ БЕСПЛАТНОСТИ: Работает исключительно с бесплатными моделями OpenRouter (:free или openrouter/free).
    """
    fallback_summary = generate_structured_summary(messages, ticker=ticker)
    if not api_key or not messages:
        return {"ai_summary": None, "structured": fallback_summary, "model": None}

    ticker_clean = ticker.strip().upper() if ticker else ""
    keywords = get_ticker_keywords(ticker_clean) if ticker_clean else []

    chosen_model = (model or DEFAULT_OPENROUTER_MODEL).strip()

    # Защита от списания средств: разрешаем только модели :free или openrouter/free
    if not (chosen_model.endswith(":free") or chosen_model == "openrouter/free"):
        return {
            "ai_summary": f"⚠️ Блокировка платной модели: разрешены только бесплатные модели OpenRouter (с суффиксом ':free' или 'openrouter/free'). Выбрана: {chosen_model}",
            "structured": fallback_summary,
            "model": chosen_model
        }

    # Отбираем только релевантные фразы строго по целевой компании
    relevant_chunks = []
    for m in messages:
        raw = m.get("text", "")
        parts = [p.strip() for p in re.split(r"(?<=[.!?\n])\s+", raw) if 35 <= len(p.strip()) <= 300]
        for p in parts:
            p_clean = re.sub(r"[\s\n]+", " ", p).strip()
            p_lower = p_clean.lower()
            if "http" in p_lower or p_clean.count("#") >= 2 or len(re.findall(r"\{\$[A-Za-z0-9_]+\}", p_clean)) >= 2:
                continue
            if ticker_clean and not any(k in p_lower for k in keywords):
                continue
            relevant_chunks.append(p_clean)

    if not relevant_chunks:
        relevant_chunks = [re.sub(r"[\s\n]+", " ", m.get("text", "")).strip() for m in messages if len(m.get("text", "")) > 40]

    # Формируем расширенный контекст для нейросети (до 35 релевантных фрагментов статей, до 12 000 символов)
    context_text = "\n".join([f"- {c}" for c in relevant_chunks[:35]])[:12000]

    url = "https://openrouter.ai/api/v1/chat/completions"
    headers = {
        "Authorization": f"Bearer {api_key.strip()}",
        "Content-Type": "application/json",
        "HTTP-Referer": "https://moexhelperdash.streamlit.app",
        "X-Title": "MOEX Helper Dash"
    }

    payload = {
        "model": chosen_model,
        "messages": [
            {
                "role": "system",
                "content": (
                    "Ты профессиональный финансовый аналитик Мосбиржи (MOEX). "
                    "Внимательно изучи мнения, статьи и факты инвесторов из Т-Банк Пульс и Smart-Lab строго по заданной компании. "
                    "Составь подробное, глубокое и структурированное резюме на русском языке:\n"
                    "1) 🟢 Ключевые драйверы роста и позитив (дивиденды, финансовые отчеты, рост прибыли);\n"
                    "2) 🔴 Основные риски и опасения (ставка ЦБ, судебные иски, налоги, конкуренция);\n"
                    "3) 📊 Ключевые цифры, котировки и факты из обсуждений;\n"
                    "4) 🎯 Итоговый вывод и консенсус для частного инвестора.\n"
                    "Пиши содержательно, опираясь на факты из статей, без лишней 'воды'."
                )
            },
            {
                "role": "user",
                "content": f"Эмитент/тикер: {ticker_clean}\n\nВыдержки из статей и обсуждений инвесторов:\n{context_text}"
            }
        ],
        "temperature": 0.3,
        "max_tokens": MAX_SUMMARY_TOKENS
    }

    try:
        resp = requests.post(url, headers=headers, json=payload, timeout=45)
        if resp.status_code == 200:
            res_data = resp.json()
            choices = res_data.get("choices", [])
            if choices:
                msg = choices[0].get("message", {})
                ai_text = str(msg.get("content") or "").strip()
                # Очищаем теги размышлений <think>...</think>, если модель поместила их в content
                ai_text = re.sub(r"<think>[\s\S]*?</think>", "", ai_text).strip()

                # Если content остался пустым, но модель сформировала reasoning
                if not ai_text and msg.get("reasoning"):
                    ai_text = str(msg.get("reasoning")).strip()

                if ai_text:
                    return {
                        "ai_summary": ai_text,
                        "structured": fallback_summary,
                        "model": chosen_model
                    }
                else:
                    return {
                        "ai_summary": f"⏳ Модель {chosen_model} потратила лимит токенов на внутренние рассуждения. Рекомендуется переключить модель на LiquidAI LFM 2.5 в боковом меню.",
                        "structured": fallback_summary,
                        "model": chosen_model
                    }
        elif resp.status_code == 401:
            return {
                "ai_summary": "❌ Неверный ключ OpenRouter API (ошибка 401). Проверьте ключ в настройках (формат sk-or-v1-...).",
                "structured": fallback_summary,
                "model": chosen_model
            }
        elif resp.status_code == 429:
            return {
                "ai_summary": f"⏳ Превышен лимит запросов к бесплатной модели {chosen_model} (ошибка 429: Rate Limit). Попробуйте переключить модель на другую бесплатную в списке или повторите через 30–60 секунд.",
                "structured": fallback_summary,
                "model": chosen_model
            }
        else:
            err_msg = resp.text[:150]
            return {
                "ai_summary": f"⚠️ Ошибка OpenRouter ({resp.status_code}): {err_msg}",
                "structured": fallback_summary,
                "model": chosen_model
            }
    except Exception as exc:
        print(f"OpenRouter API error: {exc}")

    return {"ai_summary": None, "structured": fallback_summary, "model": None}


def summarize_with_hf(messages: list, ticker: str = "", hf_token: str = None) -> dict:
    """
    Генерирует суммаризацию через Serverless Hugging Face Inference API (legacy fallback).
    """
    fallback_summary = generate_structured_summary(messages, ticker=ticker)
    if not hf_token or not messages:
        return {"ai_summary": None, "structured": fallback_summary, "model": None}

    ticker_clean = ticker.strip().upper() if ticker else ""
    keywords = get_ticker_keywords(ticker_clean) if ticker_clean else []

    relevant_chunks = []
    for m in messages:
        raw = m.get("text", "")
        parts = [p.strip() for p in re.split(r"(?<=[.!?\n])\s+", raw) if 35 <= len(p.strip()) <= 300]
        for p in parts:
            p_clean = re.sub(r"[\s\n]+", " ", p).strip()
            p_lower = p_clean.lower()
            if "http" in p_lower or p_clean.count("#") >= 2 or len(re.findall(r"\{\$[A-Za-z0-9_]+\}", p_clean)) >= 2:
                continue
            if ticker_clean and not any(k in p_lower for k in keywords):
                continue
            relevant_chunks.append(p_clean)

    if not relevant_chunks:
        relevant_chunks = [re.sub(r"[\s\n]+", " ", m.get("text", "")).strip() for m in messages if len(m.get("text", "")) > 40]

    input_text = f"Компания: {ticker_clean}. Мнения инвесторов: " + " ; ".join(relevant_chunks[:12])[:2500]

    headers = {
        "Authorization": f"Bearer {hf_token.strip()}",
        "Content-Type": "application/json"
    }

    model_name = "IlyaGusev/rut5_base_sum_gazeta"
    url = f"https://router.huggingface.co/hf-inference/models/{model_name}"

    try:
        resp = requests.post(
            url,
            headers=headers,
            json={"inputs": input_text, "parameters": {"max_length": 250, "min_length": 40}},
            timeout=15
        )
        if resp.status_code == 200:
            res_json = resp.json()
            if isinstance(res_json, list) and len(res_json) > 0:
                summary_txt = res_json[0].get("summary_text", "")
                if summary_txt:
                    return {
                        "ai_summary": summary_txt,
                        "structured": fallback_summary,
                        "model": model_name
                    }
        elif resp.status_code == 503:
            return {
                "ai_summary": "⏳ Модель на сервере Hugging Face сейчас запускается (cold start). Повторите запрос через 15–20 секунд.",
                "structured": fallback_summary,
                "model": model_name
            }
        elif resp.status_code == 402:
            return {
                "ai_summary": "⚠️ Hugging Face вернул ошибку 402 (Payment/Credits Required): на аккаунте HF исчерпаны кредиты Inference API. Hugging Face перевел серверный инференс на платную тарификацию. Ниже отображена автономная выжимка.",
                "structured": fallback_summary,
                "model": model_name
            }
        elif resp.status_code == 401:
            return {
                "ai_summary": "❌ Неверный токен Hugging Face (ошибка 401). Проверьте токен в настройках.",
                "structured": fallback_summary,
                "model": model_name
            }
    except Exception as exc:
        print(f"HF Inference error: {exc}")

    return {"ai_summary": None, "structured": fallback_summary, "model": None}

def main():
    tickers = fetch_moex_tickers()
    print(f"Starting sentiment analysis for {len(tickers)} tickers...")
    results = {}
    
    for i, ticker in enumerate(tickers):
        print(f"[{i+1}/{len(tickers)}] Analyzing {ticker}...", end=" ")
        sentiment = fetch_forum_sentiment(ticker)
        
        if sentiment is not None:
            results[ticker] = sentiment
            score = sentiment["score"]
            trend = "🟢 Positive" if score > 0 else "🔴 Negative" if score < 0 else "⚪ Neutral"
            print(f"{trend} (Score: {score})")
        else:
            print("No data")
            
        # Небольшая пауза чтобы не забанил смартлаб
        time.sleep(1)
        
    with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
        json.dump(results, f, ensure_ascii=False, indent=2)
        
    print(f"\nSaved sentiment data for {len(results)} tickers to {OUTPUT_FILE}")

if __name__ == "__main__":
    main()
