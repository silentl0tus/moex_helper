import json

filename = "Ликвидная часть (2).json"
with open(filename, 'r') as f:
    data = json.load(f)

# Hardcode moex_tickers to what it is in the dashboard currently (to emulate the bug or logic)
# Actually, I should import fetch_moex_universe to get exact moex_tickers list used in UI.
import streamlit_project as sp

sp.MIN_DAILY_TURNOVER_RUB = 0 # To simulate weekend
moex_universe = sp.fetch_moex_universe(min_turnover_rub=0)
moex_tickers = moex_universe['ticker'].tolist()

my_reserves = {}
my_blocked = {}
my_portfolio = {}

assets = {a['id']: a['symbol'] for a in data.get('assets', [])}

for t in data.get('trades', []):
    aid = t.get('asset')
    count = t.get('count', 0)
    if aid is None or count == 0: continue
    
    sym = assets.get(aid)
    if not sym: continue
        
    if sym in moex_tickers:
        target_dict = my_portfolio
    elif sym.startswith('FX') or sym in ['RUSE', 'RSHE', 'Unknown']:
        target_dict = my_blocked
    else:
        target_dict = my_reserves
    
    if sym not in target_dict:
        target_dict[sym] = {'count': 0, 'invested': 0.0}
        
    target_dict[sym]['count'] += count
    if count > 0:
        target_dict[sym]['invested'] += abs(t.get('summa', 0))
    else:
        if target_dict[sym]['count'] - count > 0:
            avg_p = target_dict[sym]['invested'] / (target_dict[sym]['count'] - count)
            target_dict[sym]['invested'] -= abs(count) * avg_p

# Filter
my_portfolio = {k: v for k, v in my_portfolio.items() if v['count'] > 0.01}
my_reserves = {k: v for k, v in my_reserves.items() if v['count'] > 0.01}
my_blocked = {k: v for k, v in my_blocked.items() if v['count'] > 0.01}

# Sum
reserves_total = sum(v['invested'] for v in my_reserves.values())
blocked_total = sum(v['invested'] for v in my_blocked.values())

cash_rub = 0.0
for cb in data.get('cash-balances', []):
    for cash_item in cb.get('cash', []):
        if cash_item.get('currency') == 'RUB':
            cash_rub += cash_item.get('value', 0)

my_reserves_invested = reserves_total + cash_rub

print("=== RESERVES BREAKDOWN ===")
print(f"Total calculated: {my_reserves_invested}")
print(f"Cash RUB: {cash_rub}")
print(f"Non-MOEX Assets:")
for k, v in my_reserves.items():
    print(f" - {k}: {v['invested']} (count: {v['count']})")
    
print("\n=== PORTFOLIO ===")
print("Stocks mapped to MOEX:")
print([k for k in my_portfolio.keys()])

