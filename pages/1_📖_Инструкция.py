import streamlit as st
import os

st.set_page_config(page_title="Документация и Инструкция", page_icon="📖", layout="wide")

st.title("📖 Документация и Инструкция")

# Читаем и показываем README
readme_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), "README.md")
if os.path.exists(readme_path):
    with open(readme_path, "r", encoding="utf-8") as f:
        readme_content = f.read()
    st.markdown(readme_content)
else:
    st.error("Файл README.md не найден в корневой директории проекта.")
