import textwrap

with open("streamlit_project.py", "r") as f:
    code = f.read()

dashboard_str = """
st.markdown("---")
d_col1, d_col2, d_col3 = st.columns(3)
d_col1.metric("Текущая фаза цикла", selected_phase.split(" ")[0])
d_col2.metric("Ключевая ставка ЦБ", f"{market_context.get('KEY_RATE', 'Н/Д')}%")
d_col3.metric("Индекс МосБиржи", f"{index_level:,.0f}" if index_level else "Н/Д")
st.markdown("---")

tab1, tab2, tab3, tab4 = st.tabs(["🏆 Рейтинг и Аналитика", "💼 Мой Портфель", "🗺️ Карта рынка", "⚖️ Ребалансировка"])
"""

# Insert tabs definition right before `with st.expander(f"Ликвидные тикеры...`
code = code.replace(
    'with st.expander(f"Ликвидные тикеры MOEX ({len(moex_tickers)})"):',
    dashboard_str + '\nwith tab1:\n    with st.expander(f"Ликвидные тикеры MOEX ({len(moex_tickers)})"):'
)

# Indent all code between `with tab1:` and the end of `if not df_fund.empty:` block?
# That's too risky. Let's just use regex to replace the sections!

old_chart = """        st.bar_chart(data=df_ranked, x="ticker", y="Health_Score")
        
        st.page_link("pages/2_💬_Сентимент_и_Пульс.py", label="Открыть детальную ленту сообщений и сентимента (Smart-Lab)", icon="💬")
        
        cols_to_show = ["ticker", "Health_Score", "Тренд", "RSI", "Сентимент", "Div_Yield_%", "Rev_Growth_%", "ROE_%", "P_E", "P_BV", "Debt_EBITDA"]
        if my_portfolio:
            cols_to_show.insert(2, "Доля в портфеле (%)")
            cols_to_show.insert(3, "PnL (%)")
            
        st.dataframe(
            df_ranked[cols_to_show], 
            width="stretch", 
            hide_index=True,
            column_config={
                "Health_Score": st.column_config.NumberColumn(
                    "Health_Score",
                    help="Комплексный рейтинг здоровья бизнеса. База = 1.0. Умножается на коэффициенты за рентабельность, долг, дивиденды и тренд. Ниже 1.0 — кандидаты на продажу."
                ),
                "Тренд": st.column_config.TextColumn(
                    "Тренд",
                    help="🔪 Падающий нож (цена ниже SMA-50 и SMA-200).\\n🚀 Восходящий тренд (пробой SMA-50).\\nБоковик (нейтрально)."
                ),
                "Сентимент": st.column_config.TextColumn(
                    "Сентимент",
                    help="Настроения на SmartLab.\\n🟢 Позитив (дает бонус)\\n🔴 Негатив (штраф)"
                ),
                "Div_Yield_%": st.column_config.NumberColumn(
                    "Div_Yield_%",
                    help="⚠️ Сжигатель капитала: если дивиденды и реальный ROE отрицательные (ниже инфляции), компания жестко штрафуется."
                ),
                "Debt_EBITDA": st.column_config.NumberColumn(
                    "Debt_EBITDA",
                    help="Долговая нагрузка. Значение выше 3.0 — красный флаг риска банкротства."
                )
            }
        )"""

# Move the bar chart and dataframe to be rendered inside tab1.
# Wait, they are currently at the bottom of `if not df_fund.empty:`.
# We want to keep them there but inside `with tab1:`. We can just indent them, but we need to do this carefully.

