import pandas as pd
from streamlit_project import fetch_fundamentals, fetch_smartlab_sentiment, score_stock

# 1. Fetch Fundamentals
df = fetch_fundamentals(['NMTP'])
if df.empty:
    print("No fundamental data for NMTP")
else:
    row = df.iloc[0].to_dict()
    print("Fundamentals:")
    for k, v in row.items():
        print(f"  {k}: {v}")

    # 2. Fetch Sentiment
    sentiment = fetch_smartlab_sentiment('NMTP')
    print(f"\nSentiment Score: {sentiment}")

    # 3. Simulate Technicals & Market Phase
    # By default in UI, tech_trend="Нейтральный (в канале)", phase="Рефляция", usd_rate=80, inflation_rate=8.0
    tech_trend = "Нейтральный (в канале)"
    selected_phase = "Рефляция (Снижение ставки, спад)"
    usd_rate = 80.0
    inflation_rate = 8.0

    print("\nCalculating Health Score:")
    # Breakdown logic
    # Base = 1.0
    base = 1.0

    # Growth Score
    growth = 1.0
    roe = row.get("ROE_%", 0)
    pe = row.get("P_E", 10)
    rev_growth = row.get("Rev_Growth_%", 0)
    
    if roe > 15: growth += 0.2
    elif roe < 0: growth -= 0.5
    if pe > 0 and pe < 8: growth += 0.2
    elif pe > 15: growth -= 0.3
    if rev_growth > 10: growth += 0.1
    elif rev_growth < 0: growth -= 0.2
    print(f"Growth Multiplier: {growth} (ROE: {roe}, P/E: {pe}, Rev_Growth: {rev_growth})")

    # Dividend Score
    div_score = 1.0
    dy = row.get("Div_Yield_%", 0)
    fcf = row.get("FCF_Yield_%", 0)
    if dy > 8: div_score += 0.3
    if fcf > dy and dy > 0: div_score += 0.1
    print(f"Dividend Multiplier: {div_score} (DY: {dy}, FCF Yield: {fcf})")

    # Sentiment Score
    sent_score = 1.0
    if sentiment > 30: sent_score += 0.1
    elif sentiment < -10: sent_score -= 0.1
    print(f"Sentiment Multiplier: {sent_score} (Sentiment: {sentiment})")

    # Risk (Debt/EBITDA, Toxic, P/BV)
    rfr_score = 1.0
    debt = row.get("Debt_EBITDA", 0)
    pbv = row.get("P_BV", 1)
    if debt > 3: rfr_score -= 0.4
    if pbv < 0.5: rfr_score += 0.1
    print(f"Risk/Value Multiplier: {rfr_score} (Debt/EBITDA: {debt}, P/BV: {pbv})")

    # Tech Multiplier
    tech_score = 1.0
    if tech_trend == "Даунтренд (Ниже SMA-50)": tech_score -= 0.2
    print(f"Tech Multiplier: {tech_score}")

    # Inflation Radar
    inf_score = 1.0
    real_dy = dy - inflation_rate
    real_roe = roe - inflation_rate
    if real_dy < -4 and real_roe < -4:
        inf_score -= 0.5
    elif real_dy > 0:
        inf_score += 0.1
    print(f"Inflation Multiplier: {inf_score} (Real DY: {real_dy}, Real ROE: {real_roe}, Inflation: {inflation_rate})")

    # Macro Phase
    macro_score = 1.0
    ticker = 'NMTP'
    if "Рефляция" in selected_phase:
        if ticker in ["IRAO", "UPRO", "HYDR", "FEES", "RTKM", "MTSS"]:
            macro_score += 0.2
        elif ticker in ["CHMF", "NLMK", "MAGN"]:
            macro_score -= 0.1
    print(f"Macro Multiplier: {macro_score}")

    final_score = base * growth * div_score * sent_score * rfr_score * tech_score * inf_score * macro_score
    print(f"\nFINAL HEALTH SCORE: {final_score}")

