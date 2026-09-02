import json

filename = "Ликвидная часть (2).json"
with open(filename, 'r') as f:
    data = json.load(f)

moex_tickers = ['MGNT', 'SBER', 'ROSN', 'NMTP', 'SVCB', 'T', 'SIBN', 'BELU', 'CHMF', 'NLMK', 'SNGS', 'TRNFP', 'GAZP'] # simplified

assets = {a['id']: a['symbol'] for a in data.get('assets', [])}
my_reserves = {}
my_blocked = {}
for t in data.get('trades', []):
    aid = t.get('asset')
    count = t.get('count', 0)
    if aid is None or count == 0: continue
    
    sym = assets.get(aid)
    if not sym: continue
        
    # We don't have the exact moex_tickers list here, so we will just print all NON-portfolio tickers
    if sym.startswith('FX') or sym in ['RUSE', 'RSHE', 'Unknown']:
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

# Print reserves
print("Reserves:")
for k, v in my_reserves.items():
    if v['count'] > 0.01:
        print(f"{k}: count={v['count']}, invested={v['invested']}")

