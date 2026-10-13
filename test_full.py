from streamlit_project import fetch_smartlab_fundamentals, load_sentiment_data, _sentiment_mtime
import pandas as pd

def test():
    df = fetch_smartlab_fundamentals(["SBER", "LKOH", "GAZP", "SVCB", "T", "BELU"])
    sentiment_data = load_sentiment_data(_cache_buster=_sentiment_mtime())
    
    def get_sent(t):
        d = sentiment_data.get(str(t).upper().strip())
        return d["score"] if d else 0.0

    def form_sent(score):
        if score > 0.1: return f"🟢 +{score:.2f}"
        elif score < -0.1: return f"🔴 {score:.2f}"
        else: return f"⚪ {score:.2f}"

    df['Сентимент_Балл'] = df['ticker'].apply(get_sent)
    df['Сентимент'] = df['Сентимент_Балл'].apply(form_sent)
    
    # Save to csv to inspect exactly what would be shown
    df[['ticker', 'Сентимент', 'Сентимент_Балл']].to_csv("test_output.csv", index=False)
    print("Done")

test()
