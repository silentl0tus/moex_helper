import requests
import pandas as pd
from io import StringIO
url = "https://smart-lab.ru/q/HEAD/f/y/"
headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"}
response = requests.get(url, headers=headers, timeout=10)
tables = pd.read_html(StringIO(response.text))
df = tables[0]
print(df.iloc[2:5].to_string())
print(df[df[0].astype(str).str.contains('ROE', case=False, na=False)].to_string())
