import textwrap

with open("streamlit_project.py", "r") as f:
    lines = f.readlines()

start_idx = next(i for i, l in enumerate(lines) if 'with st.expander(f"Ликвидные тикеры MOEX' in l)
end_idx = next(i for i, l in enumerate(lines) if 'if not df_fund.empty:' in l)

for i in range(start_idx, end_idx):
    if lines[i].strip():
        lines[i] = "    " + lines[i]

dashboard = """
st.markdown("---")
d_col1, d_col2, d_col3 = st.columns(3)
d_col1.metric("Текущая фаза цикла", selected_phase.split(" ")[0])
d_col2.metric("Ключевая ставка ЦБ", f"{market_context.get('KEY_RATE', 'Н/Д')}%")
d_col3.metric("Индекс МосБиржи", f"{index_level:,.0f}" if index_level else "Н/Д")
st.markdown("---")

tab1, tab2, tab3, tab4 = st.tabs(["🏆 Рейтинг и Аналитика", "💼 Мой Портфель", "🗺️ Карта рынка", "⚖️ Ребалансировка"])

with tab1:
"""
lines.insert(start_idx, dashboard)

port_idx = next(i for i, l in enumerate(lines) if '# 💼 АУДИТ ПОРТФЕЛЯ' in l)
bar_idx = next(i for i, l in enumerate(lines) if 'st.bar_chart(data=df_ranked' in l)
map_idx = next(i for i, l in enumerate(lines) if 'st.subheader("🗺️ Карта активов' in l)
weight_idx = next(i for i, l in enumerate(lines) if 'st.subheader("Рекомендуемые веса' in l)
else_idx = next(i for i, l in enumerate(lines) if '    else:' in l and i > weight_idx)

port_lines = lines[port_idx:bar_idx]
port_lines = [l for l in port_lines if 'st.markdown("---")' not in l and 'st.subheader("💼' not in l]
port_lines_str = "        with tab2:\n" + textwrap.indent("".join(port_lines), '    ')

bar_lines = lines[bar_idx:map_idx]
bar_lines = [l for l in bar_lines if 'st.markdown("---")' not in l]
bar_lines_str = "        with tab1:\n" + textwrap.indent("".join(bar_lines), '    ')

map_lines = lines[map_idx:weight_idx]
map_lines = [l for l in map_lines if 'st.markdown("---")' not in l and 'st.subheader("🗺️' not in l]
map_lines_str = "        with tab3:\n" + textwrap.indent("".join(map_lines), '    ')

weight_lines = lines[weight_idx:else_idx]
weight_lines = [l for l in weight_lines if 'st.markdown("---")' not in l and 'st.subheader("Рекомендуемые' not in l]
weight_lines_str = "        with tab4:\n" + textwrap.indent("".join(weight_lines), '    ')

else_lines = lines[else_idx:]

new_lines = lines[:port_idx] + [bar_lines_str, port_lines_str, map_lines_str, weight_lines_str] + else_lines

with open("streamlit_project.py", "w") as f:
    f.writelines(new_lines)
