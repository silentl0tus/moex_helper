import requests
resp = requests.get("https://api.proxyscrape.com/v2/?request=displayproxies&protocol=http&timeout=5000&country=RU&ssl=all&anonymity=all", timeout=5)
print(resp.text.strip().split('\r\n')[:10])
