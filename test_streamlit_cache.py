import streamlit as st
from streamlit_project import load_sentiment_data, _sentiment_mtime
import json

st.title("Test Cache")
data = load_sentiment_data(_cache_buster=_sentiment_mtime())
st.write("Is data empty?", len(data) == 0)
st.write("SBER score:", data.get("SBER", {}).get("score", "NOT FOUND"))
