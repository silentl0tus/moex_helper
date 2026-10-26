import pandas as pd
from streamlit_project import load_sentiment_data, _sentiment_mtime
import json

data = load_sentiment_data(_cache_buster=_sentiment_mtime())
print("Keys in sentiment_data:", len(data))
if 'SBER' in data:
    print("SBER score:", data['SBER'].get('score'))
else:
    print("SBER not found in data!")
