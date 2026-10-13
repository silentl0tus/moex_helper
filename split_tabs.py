import textwrap

with open("streamlit_project.py", "r") as f:
    code = f.read()

# Define the exact parts to split
split1 = 'with st.expander(f"Ликвидные тикеры MOEX ({len(moex_tickers)})"):'
split2 = '        # 💼 АУДИТ ПОРТФЕЛЯ'
split3 = '        st.subheader("🗺️ Карта активов: Сравнение и балансировка")'
split4 = '        st.subheader("Рекомендуемые веса в портфеле")'

# Ensure these exist
if split1 not in code or split2 not in code or split3 not in code or split4 not in code:
    print("Error: Could not find one of the split points!")
    exit(1)

# The code is inside `if not df_fund.empty:`?
# No, split1 is OUTSIDE `if not df_fund.empty:`. Wait!
# Let's check where split1 is. It's at line 529.
# `if not df_fund.empty:` is at line 662!
# So we can't just put EVERYTHING in tabs!
