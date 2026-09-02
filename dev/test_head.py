import requests
import pandas as pd
from io import StringIO

headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"}
for ticker in ["HEAD", "HHRU"]:
    url = f"https://smart-lab.ru/q/{ticker}/f/y/"
    resp = requests.get(url, headers=headers)
    print(f"Ticker {ticker} Status: {resp.status_code}")
    if resp.status_code == 200:
        try:
            tables = pd.read_html(StringIO(resp.text))
            if tables:
                print(f"Found {len(tables)} tables for {ticker}")
                print(tables[0].head(2))
        except Exception as e:
            print(f"Parsing failed for {ticker}: {e}")
