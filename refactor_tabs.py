import re

with open("streamlit_project.py", "r") as f:
    lines = f.readlines()

new_lines = []
in_tab1 = False
in_tab2 = False
in_tab3 = False
in_tab4 = False

current_tab = None

for i, line in enumerate(lines):
    # Insert Tabs initialization before the expander for liquid tickers
    if 'with st.expander(f"Ликвидные тикеры MOEX' in line:
        new_lines.append('st.markdown("---")\n')
        new_lines.append('d_col1, d_col2, d_col3 = st.columns(3)\n')
        new_lines.append('d_col1.metric("Текущая фаза цикла", selected_phase.split(" ")[0])\n')
        new_lines.append('d_col2.metric("Ключевая ставка ЦБ", f"{market_context.get(\'KEY_RATE\', \'Н/Д\')}%")\n')
        new_lines.append('d_col3.metric("Индекс МосБиржи", f"{index_level:,.0f}" if index_level else "Н/Д")\n')
        new_lines.append('st.markdown("---")\n\n')
        new_lines.append('tab1, tab2, tab3, tab4 = st.tabs(["🏆 Рейтинг и Аналитика", "💼 Мой Портфель", "🗺️ Карта рынка", "⚖️ Ребалансировка"])\n\n')
        new_lines.append('with tab1:\n')
        current_tab = 1
        new_lines.append('    ' + line)
        continue
        
    if 'st.subheader("💼 Аудит моего портфеля")' in line:
        current_tab = 2
        new_lines.append('\nwith tab2:\n')
        new_lines.append('    ' + line)
        continue

    if 'st.subheader("🗺️ Карта активов: Сравнение и балансировка")' in line:
        current_tab = 3
        new_lines.append('\nwith tab3:\n')
        new_lines.append('    ' + line)
        continue

    if 'st.subheader("Рекомендуемые веса в портфеле")' in line:
        current_tab = 4
        new_lines.append('\nwith tab4:\n')
        new_lines.append('    ' + line)
        continue

    if current_tab:
        if line.strip() == "":
            new_lines.append(line)
        else:
            new_lines.append('    ' + line)
    else:
        new_lines.append(line)

with open("streamlit_project.py", "w") as f:
    f.writelines(new_lines)
