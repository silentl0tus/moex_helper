import json

filename = "Ликвидная часть (2).json"
with open(filename, 'r') as f:
    data = json.load(f)

print(json.dumps(data.get('cash-balances'), indent=2))
