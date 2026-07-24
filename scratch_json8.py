import json
import pandas as pd
import requests

MIN_DAILY_TURNOVER_RUB = 50_000_000
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
market_is_open = max_turnover > MIN_DAILY_TURNOVER_RUB

rows = []
for ticker, list_level in data_moex["securities"]["data"]:
    if list_level not in (1, 2) and ticker not in PORTFOLIO_TICKERS: continue
    turnover_rub = turnover_by_ticker.get(ticker, 0)
    if market_is_open and turnover_rub < MIN_DAILY_TURNOVER_RUB and ticker not in PORTFOLIO_TICKERS: continue
    rows.append(ticker)
moex_tickers = rows

filename = "Ликвидная часть (2).json"
with open(filename, 'r') as f:
    data = json.load(f)

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
        continue # target_dict = my_portfolio
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

reserves_total = sum(v['invested'] for v in my_reserves.values() if v['count'] > 0.01)
print(f"Total reserves invested: {reserves_total}")
for k, v in my_reserves.items():
    if v['count'] > 0.01:
        print(f" - {k}: {v['invested']} (count: {v['count']})")
