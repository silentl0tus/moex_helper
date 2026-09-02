import json

filename = "Ликвидная часть (2).json"
with open(filename, 'r') as f:
    data = json.load(f)

# 1. Map assets
assets = {}
for a in data.get('assets', []):
    assets[a['id']] = a['symbol']

# 2. Reconstruct positions
positions = {}
for t in data.get('trades', []):
    aid = t['asset']
    count = t['count']
    if aid not in positions:
        positions[aid] = {'count': 0, 'invested': 0}
    
    positions[aid]['count'] += count
    if count > 0: # Buy
        # summa is negative for buy, so abs() or -summa is the money invested
        positions[aid]['invested'] += abs(t['summa'])
    else: # Sell
        # simple proportional reduction of invested capital
        if positions[aid]['count'] - count > 0: # Avoid div by zero
            avg_price = positions[aid]['invested'] / (positions[aid]['count'] - count)
            positions[aid]['invested'] -= abs(count) * avg_price

# 3. Print current portfolio
print("Current Portfolio:")
for aid, p in positions.items():
    if p['count'] > 0.01: # have some
        sym = assets.get(aid, "Unknown")
        avg_price = p['invested'] / p['count']
        print(f"{sym}: {p['count']} shares, Avg Buy: {avg_price:.2f}")

