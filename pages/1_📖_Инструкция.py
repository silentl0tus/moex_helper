import streamlit as st
import os

st.set_page_config(page_title="Документация и Инструкция", page_icon="📖", layout="wide")

st.title("📖 Документация и Инструкция")

# Показываем видео
st.subheader("🎬 Видеодемонстрация работы")
video_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), "dashboard_demo.mp4")
if os.path.exists(video_path):
    with open(video_path, "rb") as video_file:
        st.video(video_file.read())
else:
    st.info("💡 Чтобы добавить видеодемонстрацию, запишите экран и сохраните файл как `dashboard_demo.mp4` в корневую папку проекта.")

st.markdown("---")

# Читаем и показываем README
readme_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), "README.md")
if os.path.exists(readme_path):
    with open(readme_path, "r", encoding="utf-8") as f:
        readme_content = f.read()
    st.markdown(readme_content)
else:
    st.error("Файл README.md не найден в корневой директории проекта.")
