import yfinance as yf
try:
    tio = yf.Ticker("TIO=F").history(period="1d")
    print("Iron Ore:", tio['Close'].iloc[-1] if not tio.empty else 'Empty')
except Exception as e:
    print(e)
