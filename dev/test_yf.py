import yfinance as yf
try:
    gold = yf.Ticker("GC=F").history(period="1d")
    print("Gold:", gold['Close'].iloc[-1] if not gold.empty else 'Empty')
    # Let's try some steel symbols
    hrc = yf.Ticker("HRC=F").history(period="1d")
    print("Steel USD:", hrc['Close'].iloc[-1] if not hrc.empty else 'Empty')
except Exception as e:
    print(e)
