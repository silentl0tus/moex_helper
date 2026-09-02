import requests
import re
url = "https://cbr.ru/hd_base/KeyRate/"
headers = {"User-Agent": "Mozilla/5.0"}
response = requests.get(url, headers=headers, timeout=10)
print(response.status_code)
# Key rate is usually in a table or big text, something like 16,00 or 18,00
match = re.search(r'<td>(\d{2}[,.]\d{2})</td>', response.text)
if match:
    print("Found rate:", match.group(1))
else:
    print("No match found")
