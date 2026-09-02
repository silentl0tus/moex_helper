import requests
import pandas as pd
from io import StringIO
url = "https://smart-lab.ru/q/CHMF/f/y/"
headers = {"User-Agent": "Mozilla/5.0"}
response = requests.get(url, headers=headers, timeout=10)
tables = pd.read_html(StringIO(response.text))
df = tables[0]

# drop columns that contain "LTM"
cols_to_drop = []
for col in df.columns:
    if df[col].astype(str).str.contains('LTM').any():
        cols_to_drop.append(col)
df = df.drop(columns=cols_to_drop)

df = df.rename(columns={df.columns[0]: 'Metric'})
df = df[[c for c in df.columns if c != '?']]
for col in df.columns:
    if col != 'Metric':
        df[col] = df[col].astype(str).str.replace(r'[\s%]', '', regex=True)
df = df.drop_duplicates(subset=['Metric'], keep='first')
df = df.set_index('Metric').T
for col in df.columns:
    df[col] = pd.to_numeric(df[col], errors='coerce')
    
columns_map = {str(col).lower(): col for col in df.columns}
roe_col = next((v for k, v in columns_map.items() if 'roe' in k), None)
pe_col = next((v for k, v in columns_map.items() if 'p/e' in k or 'p / e' in k), None)

print("ROE:", df[roe_col].dropna().iloc[-1])
print("P/E:", df[pe_col].dropna().iloc[-1])
