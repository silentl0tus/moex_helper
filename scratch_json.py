import json

filename = "Ликвидная часть (2).json"
with open(filename, 'r') as f:
    data = json.load(f)

print(f"Type of root: {type(data)}")
if isinstance(data, dict):
    print("Keys:", list(data.keys()))
    
    # Just show a sample of whatever it holds
    for k in list(data.keys())[:3]:
        val = data[k]
        if isinstance(val, list) and len(val) > 0:
            print(f"Sample from {k} (list of {len(val)} items):")
            print(json.dumps(val[0], indent=2, ensure_ascii=False))
        else:
            print(f"Key {k}: {type(val)}")
elif isinstance(data, list) and len(data) > 0:
    print(f"List of {len(data)} items")
    print("Sample item:")
    print(json.dumps(data[0], indent=2, ensure_ascii=False))

