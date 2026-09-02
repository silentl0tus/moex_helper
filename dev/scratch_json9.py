import json

filename = "Ликвидная часть (2).json"
with open(filename, 'r') as f:
    data = json.load(f)

for k, v in data.items():
    if isinstance(v, list):
        for item in v:
            if isinstance(item, dict) and item.get('value') == 72732.06:
                print(f"Found 72732 in list key: {k}")
                print(item)
    elif isinstance(v, dict):
        for subk, subv in v.items():
            if subv == 72732.06:
                print(f"Found 72732 in dict key: {k} -> {subk}")
