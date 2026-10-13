import json

with open("sentiment.json", "r") as f:
    sentiment_data = json.load(f)

def get_sentiment_score(ticker):
    data = sentiment_data.get(ticker)
    return data["score"] if data else 0.0

def format_sentiment(score):
    if score > 0.1: return f"🟢 +{score:.2f}"
    elif score < -0.1: return f"🔴 {score:.2f}"
    else: return f"⚪ {score:.2f}"

tickers = ["SBER", "LKOH", "GAZP", "MOEX", "AFLT"]
for t in tickers:
    score = get_sentiment_score(t)
    print(f"{t}: {score} -> {format_sentiment(score)}")
