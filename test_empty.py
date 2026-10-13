import pandas as pd
import streamlit as st
import json

df = pd.DataFrame({
    "ticker": ["SBER", "LKOH", "GAZP"],
    "Health_Score": [1.5, 1.2, 0.9],
    "Сентимент": ["🟢 +0.70", "⚪ 0.05", "🔴 -0.30"]
})

st.dataframe(
    df,
    column_config={
        "Сентимент": st.column_config.TextColumn("Сентимент", help="test")
    }
)
