import requests
import re

url = "https://tankermap.com/market-data/urals"
headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"}

response = requests.get(url, headers=headers, timeout=10)
text = response.text

# Usually prices are near "Urals" or have specific HTML formatting like $xx.xx
# Let's search for some patterns or just print a snippet around 'Urals'
matches = re.findall(r'.{0,50}Urals.{0,50}', text, re.IGNORECASE)
print("Matches for 'Urals':")
for m in matches[:10]:
    print(m)

# Search for numbers that look like prices
price_matches = re.findall(r'\$\s*\d{2,3}\.\d{2}', text)
print("Price matches:", price_matches[:10])
