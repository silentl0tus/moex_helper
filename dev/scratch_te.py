import requests
import re
import pandas as pd
headers = {"User-Agent": "Mozilla/5.0"}
try:
    # Use pandas to read HTML tables easily
    tables = pd.read_html("https://tradingeconomics.com/commodities", storage_options={'User-Agent': 'Mozilla/5.0'})
    for i, t in enumerate(tables):
        if 'Metals' in t.columns or 'Energy' in t.columns or 'Commodity' in t.columns or 'Price' in t.columns:
            print(f"Table {i} columns:", t.columns)
            print(t.head())
except Exception as e:
    print(e)
