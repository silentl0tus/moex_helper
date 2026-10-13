import textwrap

with open("streamlit_project.py", "r") as f:
    code = f.read()

# 1. Update Sidebar Expanders
old_macro = """    st.header("Инвестиционные Часы 🕰️")
    macro_phases = [
        "Рефляция (Снижение ставки, спад)",
        "Восстановление (Низкая ставка, рост)",
        "Перегрев (Рост ставки, пик)",
        "Стагфляция (Высокая ставка, спад)"
    ]
    # Ставим Рефляцию по умолчанию, согласно вашему макро-сценарию
    selected_phase = st.selectbox("Текущая фаза экономики:", macro_phases, index=0)"""

new_macro = """    with st.expander("🌍 Макроэкономика и Часы", expanded=True):
        macro_phases = [
            "Рефляция (Снижение ставки, спад)",
            "Восстановление (Низкая ставка, рост)",
            "Перегрев (Рост ставки, пик)",
            "Стагфляция (Высокая ставка, спад)"
        ]
        # Ставим Рефляцию по умолчанию, согласно вашему макро-сценарию
        selected_phase = st.selectbox("Текущая фаза экономики:", macro_phases, index=0)"""
code = code.replace(old_macro, new_macro)

old_risk = """    st.markdown("---")
    st.subheader("Фильтры отбраковки")
    capital = st.number_input("Размер капитала, ₽", min_value=100000, value=4200000, step=100000)
    n_assets = st.slider("Число активов в портфеле", min_value=3, max_value=20, value=10, step=1,
                         help="Сколько лучших акций по Health Score войдёт в итоговый портфель.")
    max_single_name = st.slider("Макс. доля одной акции", 0.05, 0.15, 0.12, 0.01)
    rest_cap = st.slider("Макс. доля остальных акций", 0.03, 0.05, 0.05, 0.01)

    st.markdown("---")
    st.subheader("Фильтры отбраковки")
    min_roe_filter = st.slider("Мин. ROE (%)", -50.0, 30.0, 5.0, 1.0, help="Компании с ROE ниже этого значения будут удалены.")
    max_debt_filter = st.slider("Макс. Долг/EBITDA", 0.0, 20.0, 4.0, 0.5, help="Компании с Долг/EBITDA выше этого значения будут удалены.")"""

new_risk = """    with st.expander("⚖️ Риск-менеджмент портфеля", expanded=False):
        capital = st.number_input("Размер капитала, ₽", min_value=100000, value=4200000, step=100000)
        n_assets = st.slider("Число активов в портфеле", min_value=3, max_value=20, value=10, step=1,
                             help="Сколько лучших акций по Health Score войдёт в итоговый портфель.")
        max_single_name = st.slider("Макс. доля одной акции", 0.05, 0.15, 0.12, 0.01)
        rest_cap = st.slider("Макс. доля остальных акций", 0.03, 0.05, 0.05, 0.01)

    with st.expander("⚙️ Настройки отбраковки", expanded=False):
        min_roe_filter = st.slider("Мин. ROE (%)", -50.0, 30.0, 5.0, 1.0, help="Компании с ROE ниже этого значения будут удалены.")
        max_debt_filter = st.slider("Макс. Долг/EBITDA", 0.0, 20.0, 4.0, 0.5, help="Компании с Долг/EBITDA выше этого значения будут удалены.")"""
code = code.replace(old_risk, new_risk)

with open("streamlit_project.py", "w") as f:
    f.write(code)
