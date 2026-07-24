import os

import httpx
import pandas as pd
from datetime import datetime, timezone, timedelta
from dotenv import load_dotenv

load_dotenv()

class TBankGateway:
    def __init__(self, token=None):
        # Если передан аргумент - используем его, если нет - ищем в системе
        self.token = token or os.getenv("TOKEN")
        if not self.token:
            raise ValueError("Токен не найден! Передай его при инициализации или установи переменную окружения 'TOKEN'.")
        
        self.base_url = "https://invest-public-api.tinkoff.ru/rest"
        self.headers = {"Authorization": f"Bearer {self.token}"}
    
    def debug_token(self):
        # Показываем только первые 4 и последние 4 символа
        if len(self.token) > 8:
            masked = f"{self.token[:4]}...{self.token[-4:]}"
        else:
            masked = "***"
        print(f"[DEBUG] Длина ключа: {len(self.token)}, Значение: {masked}")

    def get_ticker_figi(self, ticker):
        url = f"{self.base_url}/tinkoff.public.invest.api.contract.v1.InstrumentsService/FindInstrument"
        payload = {"query": ticker}
        
        response = httpx.post(url, headers={**self.headers, "Content-Type": "application/json"}, json=payload)
        
        if response.status_code == 200:
            instruments = response.json().get('instruments', [])
            
            # Фильтруем: только акции основного рынка
            for inst in instruments:
                if inst.get('ticker') == ticker and inst.get('classCode') == 'TQBR':
                    print(f"DEBUG: Найдена акция: {inst.get('name')} | FIGI: {inst.get('figi')}")
                    return inst.get('figi')
            
            print("Акция не найдена в списке TQBR.")
            return None
        

    def get_candles(self, figi, days=30):
        print(f"DEBUG: Запрашиваю свечи для FIGI: {figi}") # ПРОВЕРКА FIGI
        
        url = f"{self.base_url}/tinkoff.public.invest.api.contract.v1.MarketDataService/GetCandles"
        
        to_date = datetime.now(timezone.utc)
        from_date = to_date - timedelta(days=days)
        
        payload = {
            "figi": figi,
            "from": from_date.isoformat(),
            "to": to_date.isoformat(),
            "interval": "CANDLE_INTERVAL_DAY"
        }
        
        headers = {**self.headers, "Content-Type": "application/json"}
        response = httpx.post(url, headers=headers, json=payload)
        
        # ВЫВОДИМ ПОЛНЫЙ ОТВЕТ СЕРВЕРА
        print(f"DEBUG: Ответ сервера: {response.text}") 
        
        if response.status_code != 200:
            print(f"Ошибка запроса: {response.status_code}")
            return pd.DataFrame()
            
        data = response.json()
        # ... (дальше логика как была)
            
        data = response.json()
        candles = data.get('candles', [])
        
        if not candles:
            print("Сервер ответил, но список свечей пуст (пустой канал).")
            return pd.DataFrame()
        
        # 4. Преобразуем ответ в удобную для Pandas структуру
        df = pd.DataFrame(candles)
        
        # Теперь выводим колонки, чтобы видеть, что пришло
        print(f"DEBUG: Структура полученного DataFrame: {df.columns.tolist()}")
        
        # Безопасное извлечение цены
        if 'close' in df.columns:
            # Если close — это словарь с units/nano
            if isinstance(df['close'].iloc[0], dict):
                df['close'] = df['close'].apply(lambda x: int(x.get('units', 0)) + int(x.get('nano', 0)) / 1e9)
            return df[['time', 'close']]
        
        return df
    
    def get_fundamentals(self, ticker):
        """Забирает фундаментальные показатели через метод FindInstrument"""
        url = f"{self.base_url}/tinkoff.public.invest.api.contract.v1.InstrumentsService/FindInstrument"
        
        payload = {"query": ticker}
        response = httpx.post(
            url, 
            headers={**self.headers, "Content-Type": "application/json"}, 
            json=payload
        )
        
        if response.status_code == 200:
            data = response.json()
            # Здесь в объекте instrument должны быть поля с фундаменталом
            # Если поле пустое, значит, для этого API нужны специальные права или метод GetBrokerReport
            return data
        return None
    def get_instrument_by_uid(self, uid):
        url = f"{self.base_url}/tinkoff.public.invest.api.contract.v1.InstrumentsService/GetInstrumentBy"
        
        # В API Т-Банка нужно передать тип ID и само значение
        payload = {
            "id_type": "INSTRUMENT_ID_TYPE_UID",
            "id": uid
        }
        
        response = httpx.post(
            url, 
            headers={**self.headers, "Content-Type": "application/json"}, 
            json=payload
        )
        
        if response.status_code == 200:
            return response.json().get('instrument')
        else:
            print(f"Ошибка получения инструмента: {response.text}")
            return None

# Использование:
print(f"DEBUG: Пытаюсь считать TOKEN...")
my_token = os.getenv("TOKEN")
print(f"DEBUG: Результат os.getenv('TOKEN'): {my_token}")

if not my_token:
    print("ВНИМАНИЕ: Переменная TOKEN пуста!")

gateway = TBankGateway(os.getenv("TOKEN"))
figi = gateway.get_ticker_figi("SBERP")
df = gateway.get_candles(figi)
print(df.head())
# info = gateway.get_fundamentals("SBER")
# print(info)
info = gateway.get_instrument_by_uid("e6123145-9665-43e0-8413-cd61b8aa9b13")
print(info)