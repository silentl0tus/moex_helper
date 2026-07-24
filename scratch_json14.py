import json
filename = "Ликвидная часть (2).json"
with open(filename, 'r') as f:
    data = json.load(f)

assets = {a['id']: a['symbol'] for a in data.get('assets', [])}
my_all = {}
for t in data.get('trades', []):
    aid = t.get('asset')
    count = t.get('count', 0)
    if aid is None or count == 0: continue
    sym = assets.get(aid)
    if not sym: continue
    
    if sym not in my_all:
        my_all[sym] = {'count': 0, 'invested': 0.0}
        
    my_all[sym]['count'] += count
    if count > 0:
        my_all[sym]['invested'] += abs(t.get('summa', 0))
    else:
        if my_all[sym]['count'] - count > 0:
            avg_p = my_all[sym]['invested'] / (my_all[sym]['count'] - count)
            my_all[sym]['invested'] -= abs(count) * avg_p

print("All non-zero positions:")
for k, v in my_all.items():
    if v['count'] > 0.01:
        print(f"{k}: count={v['count']}, invested={v['invested']}")
        
print(f"Total invested: {sum(v['invested'] for v in my_all.values() if v['count'] > 0.01)}")
