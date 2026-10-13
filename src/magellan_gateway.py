"""Шлюз данных к аналитической платформе Russian Magellan PRO (https://russianmagellan.pro).

Предоставляет:
1. Order Flow (Поток сделок, дельта покупок/продаж, кумулятивные объемы, статусы накопления/распределения).
2. Банковский сектор по РСБУ (формы 101/102 ЦБ РФ: прибыль за месяц/YTD, ROE LTM, норматив H1.0, резервы).
3. Инвестиционные программы сетевых компаний (ИПР, форма 19: капзатраты, дивиденды).
4. Раскрытия БПИФ институционалов (Т-Капитал, Ренессанс и др.).
"""

import logging
from typing import Any, Dict, List, Optional
import requests

logger = logging.getLogger(__name__)

MAGELLAN_BASE_URL = "https://russianmagellan.pro"

# Маппинг тикеров Мосбиржи на регистрационные номера Банка России
BANK_REGNUM_MAP = {
    "SBER": 1481,
    "SBERP": 1481,
    "VTBR": 1000,
    "T": 2673,
    "TCSG": 2673,
    "SVCB": 963,
    "BSPB": 436,
    "CBOM": 1978,
    "MBNK": 2268,
}


class MagellanGateway:
    def __init__(self, timeout: int = 12):
        self.base_url = MAGELLAN_BASE_URL
        self.timeout = timeout
        self.session = requests.Session()
        self.session.headers.update({
            "User-Agent": "MOEX-Helper-RoboAdvisor/2.0 (Analytics Integration)",
            "Accept": "application/json",
        })

    def get_order_flow(self, period: str = "today") -> Dict[str, Dict[str, Any]]:
        """Загружает срез Order Flow (потока сделок) за выбранный период ('today' или 'week').

        Возвращает словарь вида:
        {
            'SBER': {
                'bv': 1234567.8,         # Buy Volume (руб)
                'sv': 987654.3,          # Sell Volume (руб)
                'delta': 246913.5,       # bv - sv
                'buy_ratio': 55.6,       # % покупок
                'reading_key': 'accum',  # accum, distr, rev, calm, na
                'reading_label': '🟢 Накопление',
                'reading_explain': '...',
                'last_price': 305.2,
                'price_chng': 0.85
            },
            ...
        }
        """
        endpoint = f"{self.base_url}/api/view/{period}.json"
        try:
            resp = self.session.get(endpoint, timeout=self.timeout)
            resp.raise_for_status()
            data = resp.json()
            rows = data.get("data", [])

            result: Dict[str, Dict[str, Any]] = {}
            for item in rows:
                ticker = item.get("ticker")
                if not ticker:
                    continue

                bv = float(item.get("bv") or 0.0)
                sv = float(item.get("sv") or 0.0)
                total_vol = bv + sv
                delta = bv - sv
                buy_ratio = (bv / total_vol * 100.0) if total_vol > 0 else 50.0

                analysis = item.get("analysis") or {}
                reading = analysis.get("reading") or {}

                result[ticker] = {
                    "ticker": ticker,
                    "bv": bv,
                    "sv": sv,
                    "total_vol": total_vol,
                    "delta": delta,
                    "buy_ratio": round(buy_ratio, 1),
                    "big_bv": float(item.get("bigBv") or 0.0),
                    "big_sv": float(item.get("bigSv") or 0.0),
                    "reading_key": reading.get("key", "na"),
                    "reading_label": reading.get("label", "—"),
                    "reading_explain": reading.get("explain", ""),
                    "last_price": item.get("lastPrice"),
                    "price_chng": item.get("priceChng"),
                }
            return result
        except Exception as exc:
            logger.warning("Ошибка загрузки Order Flow из Magellan (%s): %s", period, exc)
            return {}

    def get_banks_summary(self) -> Dict[str, Dict[str, Any]]:
        """Загружает сводный реестр банков по РСБУ (формы 101/102 ЦБ РФ)."""
        endpoint = f"{self.base_url}/api/view/banks/index.json"
        try:
            resp = self.session.get(endpoint, timeout=self.timeout)
            resp.raise_for_status()
            data = resp.json()
            banks_list = data.get("banks", [])

            banks_by_reg: Dict[int, Dict[str, Any]] = {
                b["regnum"]: b for b in banks_list if "regnum" in b
            }

            result: Dict[str, Dict[str, Any]] = {}
            for ticker, regnum in BANK_REGNUM_MAP.items():
                if regnum in banks_by_reg:
                    b_info = banks_by_reg[regnum]
                    result[ticker] = {
                        "ticker": ticker,
                        "regnum": regnum,
                        "name": b_info.get("name"),
                        "last_month": b_info.get("last_month"),
                        "ytd_profit_rub": b_info.get("ytd", 0) * 1000,  # ЦБ дает в тыс. руб.
                        "ytd_prev_rub": b_info.get("ytd_prev", 0) * 1000,
                        "prev_year_rub": b_info.get("prev_year", 0) * 1000,
                        "ytd_growth_pct": round(
                            (b_info.get("ytd", 0) / b_info.get("ytd_prev", 1) - 1.0) * 100.0, 1
                        ) if b_info.get("ytd_prev") else None,
                    }
            return result
        except Exception as exc:
            logger.warning("Ошибка загрузки банков из Magellan: %s", exc)
            return {}

    def get_bank_details(self, regnum_or_ticker: Any) -> Optional[Dict[str, Any]]:
        """Загружает детальный месячный финансовый профиль банка (включая H1.0, ROE LTM, резервы)."""
        regnum = BANK_REGNUM_MAP.get(str(regnum_or_ticker).upper(), regnum_or_ticker)
        try:
            regnum = int(regnum)
        except (ValueError, TypeError):
            return None

        endpoint = f"{self.base_url}/api/view/banks/{regnum}.json"
        try:
            resp = self.session.get(endpoint, timeout=self.timeout)
            if resp.status_code != 200:
                return None
            data = resp.json()

            points = data.get("points", [])
            health = data.get("health", [])
            latest_point = points[-1] if points else {}
            latest_health = health[-1] if health else {}

            return {
                "regnum": regnum,
                "name": data.get("name"),
                "roe_ltm": data.get("roe_ltm"),
                "h1_0": data.get("h1_0"),  # Достаточность совокупного капитала (норматив >= 8.0%)
                "h1_1": data.get("h1_1"),  # Достаточность базового капитала (норматив >= 4.5%)
                "norm_month": data.get("norm_month"),
                "last_month": latest_point.get("month"),
                "monthly_profit_rub": latest_point.get("monthly", 0) * 1000 if latest_point.get("monthly") else None,
                "ytd_profit_rub": latest_point.get("ytd", 0) * 1000 if latest_point.get("ytd") else None,
                "overdue_pct": latest_health.get("overdue_pct"),
                "reserve_cover": latest_health.get("reserve_cover"),
                "points": points,
            }
        except Exception as exc:
            logger.warning("Ошибка загрузки деталей банка regnum=%s: %s", regnum, exc)
            return None

    def get_funds_flow(self) -> List[Dict[str, Any]]:
        """Загружает состав и раскрытия сделок институциональных БПИФ (Т-Капитал, Ренессанс)."""
        endpoint = f"{self.base_url}/api/view/funds.json"
        try:
            resp = self.session.get(endpoint, timeout=self.timeout)
            resp.raise_for_status()
            data = resp.json()
            return data.get("funds", [])
        except Exception as exc:
            logger.warning("Ошибка загрузки данных фондов: %s", exc)
            return []

    def get_ipr_plans(self) -> Dict[str, Any]:
        """Загружает финпланы и инвестпрограммы (ИПР) сетевых компаний."""
        endpoint = f"{self.base_url}/api/view/ipr.json"
        try:
            resp = self.session.get(endpoint, timeout=self.timeout)
            resp.raise_for_status()
            return resp.json()
        except Exception as exc:
            logger.warning("Ошибка загрузки данных ИПР: %s", exc)
            return {}
