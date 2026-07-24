import requests
import pandas as pd
from io import StringIO
url = "https://cbr.ru/hd_base/KeyRate/"
headers = {"User-Agent": "Mozilla/5.0"}
response = requests.get(url, headers=headers, timeout=10)
tables = pd.read_html(StringIO(response.text))
df = tables[0]
print(df.head())
