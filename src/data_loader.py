import os
from pathlib import Path

import streamlit as st
import pandas as pd


def _load_env_file():
    env_path = Path(__file__).with_name(".env")
    if not env_path.exists():
        return

    for raw_line in env_path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if key and key not in os.environ:
            os.environ[key] = value


_load_env_file()

try:
    from datahub_api import DataHub
except ImportError:
    DataHub = None

# Кешируем данные, чтобы не дергать API при каждом клике пользователя
@st.cache_data(ttl=3600) # ttl=3600 значит обновлять данные раз в час
def get_smartlab_data(ticker):
    client = DataHub()
    # Логика получения данных (зависит от того, что именно ты хочешь взять)
    data = client.get_data(ticker) 
    return pd.DataFrame(data)