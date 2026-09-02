import requests
import re
import json
import time
from pathlib import Path

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

# Резервный список (если MOEX API недоступен)
FALLBACK_TICKERS = [
    "SBER", "SBERP", "LKOH", "GAZP", "ROSN", "NVTK", "YNDX", "YDEX", "T", "TCSG", 
    "PLZL", "MGNT", "CHMF", "NLMK", "SNGS", "SNGSP", "MTSS", "TATN", "TRNFP", 
    "SVCB", "HEAD", "ASTR", "DIAS", "DATA", "POSI", "OZON", "MOEX", "AFKS", 
    "FLOT", "ALRS", "BANE", "BANEP", "RNFT", "SOFL", "VKCO", "MAGN", "PIKK"
]

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

def fetch_forum_sentiment(ticker):
    url = f"https://smart-lab.ru/forum/{ticker}"
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36"
    }
    
    try:
        response = requests.get(url, headers=headers, timeout=10)
        if response.status_code != 200:
            return None
            
        posts = re.findall(r'class="comment_body[^>]*>(.*?)</div>', response.text, re.DOTALL | re.IGNORECASE)
        if not posts:
            posts = re.findall(r'<div class="text[^>]*>(.*?)</div>', response.text, re.DOTALL | re.IGNORECASE)
            
        if not posts:
            return None
            
        total_pos = 0
        total_neg = 0
        
        for post in posts[:20]: # Берем последние 20 постов
            clean_text = clean_html(post)
            p, n = analyze_sentiment(clean_text)
            total_pos += p
            total_neg += n
            
        # Нормализация скора от -1.0 до 1.0
        if total_pos == 0 and total_neg == 0:
            score = 0.0
        else:
            score = (total_pos - total_neg) / (total_pos + total_neg + 1) # +1 чтобы избежать деления на 0 и сгладить редкие посты
            
        return {
            "score": round(score, 2),
            "pos_words": total_pos,
            "neg_words": total_neg,
            "posts_analyzed": len(posts[:20]),
            "timestamp": time.time()
        }
        
    except Exception as e:
        print(f"Error fetching {ticker}: {e}")
        return None

def extract_meaningful_messages(ticker, max_pages=2, max_messages=50):
    from bs4 import BeautifulSoup
    
    messages = []
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
    }
    
    for page in range(1, max_pages + 1):
        if page == 1:
            url = f"https://smart-lab.ru/forum/{ticker}"
        else:
            url = f"https://smart-lab.ru/forum/{ticker}/page{page}/"
            
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
                author = author_tag.get_text(strip=True) if author_tag else "Аноним"
                
                # Получаем время
                time_tag = it.select_one('time, .time, .date')
                time_str = time_tag.get_text(strip=True) if time_tag else ""
                if not time_str and time_tag and time_tag.get('datetime'):
                    time_str = time_tag.get('datetime')
                    
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
                    "author": author,
                    "time": time_str,
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

def extract_pulse_messages(ticker, max_messages=50):
    url = f"https://www.tbank.ru/api/invest-gw/social/v1/post/instrument/{ticker}?limit={max_messages}"
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
        "Accept": "application/json"
    }
    
    messages = []
    try:
        r = requests.get(url, headers=headers, timeout=10)
        if r.status_code != 200:
            return messages
            
        data = r.json()
        items = data.get("payload", {}).get("items", [])
        
        for item in items:
            raw_text = item.get("content", {}).get("text", "")
            if not raw_text or len(raw_text) < 30:
                continue
                
            author = item.get("nickname", "Аноним")
            
            # Парсинг времени (формат: 2026-09-02T11:14:03.794Z)
            time_str = item.get("inserted", "")
            if time_str:
                try:
                    # Попытка преобразовать в более читаемый вид
                    from datetime import datetime
                    dt = datetime.strptime(time_str.split('.')[0].replace('Z', ''), "%Y-%m-%dT%H:%M:%S")
                    time_str = dt.strftime("%Y-%m-%d %H:%M")
                except:
                    pass
            
            post_id = item.get("id", "")
            link = f"https://www.tbank.ru/invest/social/profile/{author}/{post_id}/" if author != "Аноним" and post_id else url
            
            # Очищаем текст от базовых спецсимволов для анализа (Пульс отдает чистый текст, но могут быть смайлы)
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
                "author": author,
                "time": time_str,
                "text": raw_text,
                "link": link,
                "pos": p,
                "neg": n,
                "analytics": a_count,
                "trend": trend
            })
            
    except Exception as e:
        print(f"Error fetching Pulse detailed {ticker}: {e}")
        
    return messages

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
