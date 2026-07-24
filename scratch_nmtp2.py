import pandas as pd
import streamlit_project as sp

df = sp.fetch_smartlab_fundamentals(['NMTP'])
if df.empty:
    print("No fundamental data for NMTP")
else:
    row = df.iloc[0].to_dict()
    print("Fundamentals:")
    for k, v in row.items():
        print(f"  {k}: {v}")

