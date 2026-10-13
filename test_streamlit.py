import pandas as pd
from streamlit_project import fetch_smartlab_fundamentals, load_sentiment_data, _sentiment_mtime, fetch_technical_indicators, apply_tech_multiplier

sentiment_data = load_sentiment_data(_mtime=_sentiment_mtime())

def get_sentiment_score(ticker):
    data = sentiment_data.get(ticker)
    return data["score"] if data else 0.0

def format_sentiment(score):
    if score > 0.1: return f"🟢 +{score:.2f}"
    elif score < -0.1: return f"🔴 {score:.2f}"
    else: return f"⚪ {score:.2f}"

df_fund = fetch_smartlab_fundamentals(["SBER", "GAZP", "LKOH"])
tech_data = fetch_technical_indicators(["SBER", "GAZP", "LKOH"])
df_fund = pd.merge(df_fund, tech_data, on="ticker", how="left")

df_fund['Сентимент_Балл'] = df_fund['ticker'].apply(get_sentiment_score)
df_fund['Сентимент'] = df_fund['Сентимент_Балл'].apply(format_sentiment)

print(df_fund[['ticker', 'Сентимент']])
