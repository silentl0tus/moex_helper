import requests
import re
from bs4 import BeautifulSoup

headers = {"User-Agent": "Mozilla/5.0"}
url = "https://cbr.ru/"
try:
    resp = requests.get(url, headers=headers, timeout=5)
    # The CBR homepage has a section for Key Indicators which includes Inflation
    soup = BeautifulSoup(resp.text, 'html.parser')
    # Let's find all text containing "%"
    divs = soup.find_all('div', class_='indicator_el')
    for div in divs:
        print(div.text.strip().replace('\n', ' '))
except Exception as e:
    print(e)
