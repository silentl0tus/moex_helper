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

# Топ-ликвидных тикеров для анализа
TICKERS_TO_SCAN = [
    "SBER", "SBERP", "LKOH", "GAZP", "ROSN", "NVTK", "YNDX", "YDEX", "T", "TCSG", 
    "PLZL", "MGNT", "CHMF", "NLMK", "SNGS", "SNGSP", "MTSS", "TATN", "TRNFP", 
    "SVCB", "HEAD", "ASTR", "DIAS", "DATA", "POSI", "OZON", "MOEX", "AFKS", 
    "FLOT", "ALRS", "BANE", "BANEP", "RNFT", "SOFL", "VKCO", "MAGN", "PIKK"
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

def main():
    print(f"Starting sentiment analysis for {len(TICKERS_TO_SCAN)} tickers...")
    results = {}
    
    for i, ticker in enumerate(TICKERS_TO_SCAN):
        print(f"[{i+1}/{len(TICKERS_TO_SCAN)}] Analyzing {ticker}...", end=" ")
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
        
    print(f"\nSaved sentiment data to {OUTPUT_FILE}")

if __name__ == "__main__":
    main()
