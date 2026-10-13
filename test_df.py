import pandas as pd
from streamlit_project import fetch_smartlab_fundamentals, load_sentiment_data, _sentiment_mtime

sentiment_data = load_sentiment_data(_mtime=_sentiment_mtime())
print(f"Loaded sentiment data keys: {len(sentiment_data)}")

df = fetch_smartlab_fundamentals(["SBER", "GAZP", "LKOH"])
if 'Сентимент' in df.columns:
    print(df[['ticker', 'Сентимент']])
else:
    print("Column not found!")
