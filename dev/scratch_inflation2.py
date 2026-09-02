import requests
import re

headers = {"User-Agent": "Mozilla/5.0"}
url = "https://cbr.ru/"
try:
    resp = requests.get(url, headers=headers, timeout=5)
    # The inflation value usually comes with "Инфляция" in Russian.
    match = re.search(r'Инфляция.*?(\d{1,2}[,.]\d{1,2})\s*%', resp.text, re.IGNORECASE | re.DOTALL)
    if match:
        print(f"CBR Inflation: {match.group(1)}%")
    else:
        print("Not found with generic search. Let's look for specific div classes.")
        # Sometimes it's inside <div class="main-indicator_value">
        matches = re.findall(r'<div class="main-indicator_value">([^<]+)</div>', resp.text)
        print("Main indicators:", matches)
except Exception as e:
    print(e)
