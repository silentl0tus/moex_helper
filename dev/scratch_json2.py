import json

filename = "Ликвидная часть (2).json"
with open(filename, 'r') as f:
    data = json.load(f)

assets = data.get('assets', [])
if len(assets) > 0:
    print(f"Found {len(assets)} assets. Sample of first 2:")
    for a in assets[:2]:
        print(json.dumps(a, indent=2, ensure_ascii=False))
else:
    print("No assets found.")

