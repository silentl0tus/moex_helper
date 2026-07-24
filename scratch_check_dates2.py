import requests
import pandas as pd
import datetime

one_year_ago = (datetime.datetime.now() - datetime.timedelta(days=365)).strftime("%Y-%m-%d")
url = "https://iss.moex.com/iss/engines/stock/markets/shares/boards/TQBR/securities/SBER/candles.json"
params = {"interval": 24, "from": one_year_ago}

resp = requests.get(url, params=params)
data = resp.json()
df = pd.DataFrame(data['candles']['data'], columns=data['candles']['columns'])
print("Total rows:", len(df))
print("Last date:", df['begin'].iloc[-1])
