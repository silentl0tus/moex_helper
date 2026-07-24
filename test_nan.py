import pandas as pd
df = pd.DataFrame({'Div_RUB': [10.0, 20.0], 'Current_Price': [100.0, float('nan')]})
print(df['Div_RUB'] / df['Current_Price'])
