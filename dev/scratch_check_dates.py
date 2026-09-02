import requests
import pandas as pd

url = "https://iss.moex.com/iss/engines/stock/markets/shares/boards/TQBR/securities/SBER/candles.json"
# To get the LAST 500 candles, we can pass `from=2023-01-01` but we don't know the exact count.
# Or we can get the total size from cursor, but it's easier to just pass a date 2 years ago.
import datetime
two_years_ago = (datetime.datetime.now() - datetime.timedelta(days=700)).strftime("%Y-%m-%d")
params = {"interval": 24, "from": two_years_ago}

resp = requests.get(url, params=params)
data = resp.json()
df = pd.DataFrame(data['candles']['data'], columns=data['candles']['columns'])
print("Total rows:", len(df))
print("First date:", df['begin'].iloc[0])
print("Last date:", df['begin'].iloc[-1])
