
#
# import requests
#
# # Делаем запрос к серверу
# url = "https://iss.moex.com/iss/engines/stock/markets/shares/boards/TQBR/securities.json"
# params = {
#     "iss.meta": "off",
#     "iss.only": "marketdata",
#     "marketdata.columns": "SECID"
# }
# response = requests.get(url, params=params)
# response.raise_for_status()  # проверка на ошибку
#
# # Извлекаем тикеры
# data = response.json()
# tickers = [item[0] for item in data['marketdata']['data']]
#
# # Формируем строку
# security_codes_str = f"security_codes = {tuple(tickers)}"
# print(security_codes_str)


import requests

url = "https://iss.moex.com/iss/engines/stock/markets/shares/boards/TQBR/securities.json"

params = {
    "iss.meta": "off",
    "iss.only": "securities", # Переключаем канал с цен на "паспорта" акций
    "securities.columns": "SECID,LISTLEVEL" # Просим вернуть только тикер и уровень листинга
}

response = requests.get(url, params=params)
response.raise_for_status()

# Извлекаем данные
data = response.json()

# Проходимся по всем строкам ответа и собираем только 1 и 2 эшелон
top_tier_tickers = []
for row in data['securities']['data']:
    ticker = row[0]
    list_level = row[1]
    
    # Логический фильтр: пропускаем только уровни 1 и 2
    if list_level in [1, 2]:
        top_tier_tickers.append(ticker)

print(f"Найдено качественных активов: {len(top_tier_tickers)}")
security_codes_str = f"security_codes = {tuple(top_tier_tickers)}"
print(security_codes_str)