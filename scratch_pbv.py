import requests
import pandas as pd
from io import StringIO
url = "https://smart-lab.ru/q/SNGS/f/y/"
headers = {"User-Agent": "Mozilla/5.0"}
response = requests.get(url, headers=headers, timeout=10)
tables = pd.read_html(StringIO(response.text))
df = tables[0]
df = df.rename(columns={df.columns[0]: 'Metric'})
df = df[[c for c in df.columns if c != '?']]
for col in df.columns:
    if col != 'Metric':
        df[col] = df[col].astype(str).str.replace(r'[\s%]', '', regex=True)
df = df.drop_duplicates(subset=['Metric'], keep='first')
print(df[df['Metric'].str.contains('P/B', case=False, na=False)].to_string())
