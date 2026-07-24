import json

filename = "Ликвидная часть (2).json"
with open(filename, 'r') as f:
    data = json.load(f)

trades = data.get('trades', [])
sells = [t for t in trades if t.get('summa', 0) > 0]
if len(sells) > 0:
    print("Found a sell trade:")
    print(json.dumps(sells[0], indent=2, ensure_ascii=False))
else:
    print("No sell trades found.")

