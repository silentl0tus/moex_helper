import json

filename = "Ликвидная часть (2).json"
with open(filename, 'r') as f:
    data = json.load(f)

trades = data.get('trades', [])
if len(trades) > 0:
    print(f"Found {len(trades)} trades. Sample of first 1:")
    print(json.dumps(trades[0], indent=2, ensure_ascii=False))

    # Calculate positions by summing quantities for each asset ID
    positions = {}
    for t in trades:
        aid = t.get('asset_id', t.get('asset'))  # might be named 'asset'
        if aid is None: continue
        qty = t.get('quantity', t.get('q', 0))
        # Wait, let's check trade structure first
else:
    print("No trades found.")

