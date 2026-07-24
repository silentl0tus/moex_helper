import streamlit_project
import pandas as pd

# Test the tech function directly
tickers = ["SBER", "GAZP"]
tech_df = streamlit_project.fetch_technical_indicators(tickers)
print("Tech Data:")
print(tech_df)

