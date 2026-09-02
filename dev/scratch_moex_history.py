import requests
import time
import pandas as pd
from concurrent.futures import ThreadPoolExecutor

TICKERS = ["SBER", "LKOH", "GAZP", "YNDX", "MOEX"] # Test with 5

def fetch_candles(ticker):
    url = f"https://iss.moex.com/iss/engines/stock/markets/shares/boards/TQBR/securities/{ticker}/candles.json"
    params = {
        "interval": 24, # daily
        "start": 0,
        "from": "2024-01-01" # Get last few years
    }
    resp = requests.get(url, params=params, timeout=5)
    data = resp.json()
    if 'candles' in data and data['candles']['data']:
        df = pd.DataFrame(data['candles']['data'], columns=data['candles']['columns'])
        return ticker, len(df)
    return ticker, 0

start = time.time()
with ThreadPoolExecutor(max_workers=10) as ex:
    results = list(ex.map(fetch_candles, TICKERS))
print(f"Time taken: {time.time()-start:.2f}s for {len(TICKERS)} tickers")
print(results)
