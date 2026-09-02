import requests

MOEX_TQBR_URL = "https://iss.moex.com/iss/engines/stock/markets/shares/boards/TQBR/securities.json"
MIN_DAILY_TURNOVER_RUB = 50_000_000

params = {
    "iss.meta": "off",
    "iss.only": "securities,marketdata",
    "securities.columns": "SECID,LISTLEVEL",
    "marketdata.columns": "SECID,VALTODAY",
}

response = requests.get(MOEX_TQBR_URL, params=params, timeout=30)
response.raise_for_status()
data = response.json()

turnover_by_ticker = {
    row[0]: row[1] or 0
    for row in data["marketdata"]["data"]
}

top_tier_tickers = []
excluded_low_liquidity = []
for ticker, list_level in data["securities"]["data"]:
    if list_level not in (1, 2):
        continue
    turnover_rub = turnover_by_ticker.get(ticker, 0)
    if turnover_rub < MIN_DAILY_TURNOVER_RUB:
        excluded_low_liquidity.append(ticker)
        continue
    top_tier_tickers.append(ticker)

top_tier_tickers.sort()
print(f"Найдено ликвидных активов (оборот >= {MIN_DAILY_TURNOVER_RUB // 1_000_000} млн ₽): {len(top_tier_tickers)}")
print(f"Исключено неликвидных: {len(excluded_low_liquidity)}")
security_codes_str = f"security_codes = {tuple(top_tier_tickers)}"
print(security_codes_str)
