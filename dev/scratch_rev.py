import requests
import pandas as pd
from io import StringIO
for ticker in ["LKOH", "SBER"]:
    url = f"https://smart-lab.ru/q/{ticker}/f/y/"
    headers = {"User-Agent": "Mozilla/5.0"}
    response = requests.get(url, headers=headers, timeout=10)
    tables = pd.read_html(StringIO(response.text))
    df = tables[0]
    cols_to_drop = [col for col in df.columns if df[col].astype(str).str.contains('LTM', case=False).any()]
    if cols_to_drop:
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
    rev_col = next((v for k, v in columns_map.items() if 'выручка' in k or 'чист. операц' in k or 'чистый операц' in k), None)
    if rev_col:
        series = df[rev_col].dropna()
        if len(series) >= 2:
            last = series.iloc[-1]
            prev = series.iloc[-2]
            growth = ((last - prev) / abs(prev)) * 100 if prev != 0 else 0
            print(f"{ticker}: {rev_col} -> {last} vs {prev} = {growth:.2f}%")
