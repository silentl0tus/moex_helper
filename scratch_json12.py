import json

filename = "Ликвидная часть (2).json"
with open(filename, 'r') as f:
    data = json.load(f)

assets = {a['id']: a['symbol'] for a in data.get('assets', [])}

for t in data.get('trades', []):
    aid = t.get('asset')
    sym = assets.get(aid)
    count = t.get('count', 0)
    if aid is None or count == 0: continue
    print(f"Trade: {sym} count={count} summa={t.get('summa', 0)}")
    
