import json

filename = "Ликвидная часть (2).json"
with open(filename, 'r') as f:
    data = json.load(f)

# Use exact logic from streamlit_project.py

moex_tickers = ['MGNT', 'SBER', 'ROSN', 'NMTP', 'SVCB', 'T', 'SIBN', 'BELU', 'CHMF', 'NLMK', 'SNGS', 'TRNFP', 'GAZP']
# wait, what if moex_tickers in the real code contains more? 
# The UI has `fetch_moex_universe(0)` because it's weekend!
import requests
MOEX_TQBR_URL = "https://iss.moex.com/iss/engines/stock/markets/shares/boards/TQBR/securities.json"
PORTFOLIO_TICKERS = ['MGNT', 'SBER', 'ROSN', 'NMTP', 'SVCB', 'T', 'SIBN', 'BELU', 'CHMF', 'NLMK', 'SNGS', 'TRNFP', 'GAZP']
params = {
    "iss.meta": "off",
    "iss.only": "securities,marketdata",
    "securities.columns": "SECID,LISTLEVEL",
    "marketdata.columns": "SECID,VALTODAY",
}
response = requests.get(MOEX_TQBR_URL, params=params, timeout=30)
data_moex = response.json()
turnover_by_ticker = {row[0]: row[1] or 0 for row in data_moex["marketdata"]["data"]}
max_turnover = max(turnover_by_ticker.values()) if turnover_by_ticker else 0
market_is_open = max_turnover > 50000000

rows = []
for ticker, list_level in data_moex["securities"]["data"]:
    if list_level not in (1, 2) and ticker not in PORTFOLIO_TICKERS:
        continue
    turnover_rub = turnover_by_ticker.get(ticker, 0)
    if market_is_open and turnover_rub < 50000000 and ticker not in PORTFOLIO_TICKERS:
        continue
    rows.append(ticker)
moex_tickers = rows

my_portfolio = {}
my_reserves_invested = 0.0
my_blocked_invested = 0.0

assets = {a['id']: a['symbol'] for a in data.get('assets', [])}

my_reserves = {}
my_blocked = {}
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

# Фильтруем закрытые позиции
my_portfolio = {k: v for k, v in my_portfolio.items() if v['count'] > 0.01}
my_reserves = {k: v for k, v in my_reserves.items() if v['count'] > 0.01}
my_blocked = {k: v for k, v in my_blocked.items() if v['count'] > 0.01}

# Считаем сумму в резервах
reserves_total = sum(v['invested'] for v in my_reserves.values())
blocked_total = sum(v['invested'] for v in my_blocked.values())

cash_rub = 0.0
for cb in data.get('cash-balances', []):
    for cash_item in cb.get('cash', []):
        if cash_item.get('currency') == 'RUB':
            cash_rub += cash_item.get('value', 0)
            
my_reserves_invested = reserves_total + cash_rub
my_blocked_invested = blocked_total

print(f"my_reserves_invested: {my_reserves_invested}")
for k, v in my_reserves.items():
    print(f"Reserves: {k} = {v['invested']}")
print(f"Cash RUB = {cash_rub}")

