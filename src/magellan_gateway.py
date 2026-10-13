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



# Маппинг тикеров акций на ключевые слова эмитентов корпоративных облигаций
TICKER_BOND_KEYWORD_MAP = {
    "SBER": ["СБЕР"],
    "SBERP": ["СБЕР"],
    "GAZP": ["ГАЗПРОМ"],
    "LKOH": ["ЛУКОЙЛ"],
    "ROSN": ["РОСНЕФТ"],
    "NVTK": ["НОВАТЭК"],
    "GMKN": ["НОРИЛЬСК", "ГМК"],
    "CHMF": ["СЕВЕРСТАЛ"],
    "NLMK": ["НЛМК"],
    "MAGN": ["ММК", "МАГНИТОГОРСК"],
    "PLZL": ["ПОЛЮС"],
    "ALRS": ["АЛРОСА"],
    "VTBR": ["ВТБ"],
    "T": ["Т-БАНК", "ТИНЬКОФФ", "ТКС"],
    "TCSG": ["Т-БАНК", "ТИНЬКОФФ", "ТКС"],
    "SVCB": ["СОВКОМБАНК"],
    "BSPB": ["САНКТ-ПЕТЕРБУРГ"],
    "MTSS": ["МТС"],
    "MGNT": ["МАГНИТ"],
    "SMLT": ["САМОЛЕТ"],
    "SGZH": ["СЕГЕЖ"],
    "AFLT": ["АЭРОФЛОТ"],
    "RTKM": ["РОСТЕЛЕКОМ"],
    "RTKMP": ["РОСТЕЛЕКОМ"],
    "PHOR": ["ФОСАГРО"],
    "TATN": ["ТАТНЕФТ"],
    "TATNP": ["ТАТНЕФТ"],
    "SIBN": ["ГАЗПРОМ НЕФТ"],
    "TRNFP": ["ТРАНСНЕФТ"],
    "FLOT": ["СОВКОМФЛОТ"],
    "AFKS": ["СИСТЕМА"],
    "SELG": ["СЕЛИГДАР"],
    "MVID": ["М.ВИДЕО", "МВИДЕО"],
    "PIKK": ["ПИК"],
    "OZON": ["ОЗОН"],
    "VKCO": ["ВК", "VK"],
}

class MagellanGateway:
    def __init__(self, timeout: int = 12):
        self.base_url = MAGELLAN_BASE_URL
        self.timeout = timeout
        self.session = requests.Session()
        self.session.headers.update({
            "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36",
            "Accept": "application/json, text/plain, */*",
            "Referer": "https://russianmagellan.pro/",
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

    def get_bonds_stress_radar(self) -> Dict[str, Dict[str, Any]]:
        """Загружает базу корпоративных облигаций Magellan и живые доходности TQCB с Московской биржи (MOEX ISS).

        Определяет долговой стресс компаний: если доходность бондов взлетает > 28-30%+,
        это опережающий сигнал критического финансового риска / реструктуризации долга.
        """
        bonds_endpoint = f"{self.base_url}/api/market/company-bonds"
        moex_endpoint = "http://iss.moex.com/iss/engines/stock/markets/bonds/boards/TQCB/securities.json?iss.meta=off&iss.only=marketdata&marketdata.columns=SECID,YIELD,DURATION"

        try:
            # 1. Загрузка справочника облигаций
            resp_mag = self.session.get(bonds_endpoint, timeout=self.timeout)
            resp_mag.raise_for_status()
            mag_bonds = resp_mag.json().get("rows", [])
            mag_by_secid = {b["secid"]: b for b in mag_bonds if "secid" in b}

            # 2. Загрузка живых доходностей MOEX
            resp_moex = requests.get(moex_endpoint, timeout=self.timeout)
            resp_moex.raise_for_status()
            moex_md = resp_moex.json().get("marketdata", {}).get("data", [])

            ticker_bonds: Dict[str, List[Dict[str, Any]]] = {t: [] for t in TICKER_BOND_KEYWORD_MAP}

            for row in moex_md:
                if not row or len(row) < 2:
                    continue
                secid, yield_val, duration = row[0], row[1], row[2]
                if yield_val is not None and 0 < yield_val < 150:
                    mag_info = mag_by_secid.get(secid)
                    if mag_info:
                        target_str = ((mag_info.get("name") or "") + " " + (mag_info.get("issuer") or "")).upper()
                        for ticker, keywords in TICKER_BOND_KEYWORD_MAP.items():
                            if any(kw in target_str for kw in keywords):
                                ticker_bonds[ticker].append({
                                    "secid": secid,
                                    "name": mag_info.get("name"),
                                    "yield": float(yield_val),
                                    "duration": duration,
                                })

            result: Dict[str, Dict[str, Any]] = {}
            for ticker, blist in ticker_bonds.items():
                if blist:
                    yields = [b["yield"] for b in blist]
                    avg_y = sum(yields) / len(yields)
                    max_y = max(yields)
                    min_y = min(yields)

                    if max_y >= 50.0:
                        status = "🚨 Преддефолтный спред (YTM > 50%)"
                        risk_level = "CRITICAL"
                        penalty_mult = 0.45
                    elif max_y >= 28.0:
                        status = "⚠️ Высокий долговой стресс (YTM > 28%)"
                        risk_level = "HIGH"
                        penalty_mult = 0.70
                    elif max_y >= 18.0:
                        status = "🟡 Повышенный спред к ОФЗ (YTM > 18%)"
                        risk_level = "MEDIUM"
                        penalty_mult = 1.0
                    else:
                        status = "🟢 Высокая надежность долга (YTM < 18%)"
                        risk_level = "SAFE"
                        penalty_mult = 1.05

                    sorted_b = sorted(blist, key=lambda x: x["yield"], reverse=True)
                    sample = sorted_b[0]

                    result[ticker] = {
                        "ticker": ticker,
                        "bond_count": len(blist),
                        "avg_ytm": round(avg_y, 2),
                        "max_ytm": round(max_y, 2),
                        "min_ytm": round(min_y, 2),
                        "distress_status": status,
                        "risk_level": risk_level,
                        "health_mult": penalty_mult,
                        "sample_name": sample.get("name"),
                        "sample_ytm": round(sample.get("yield", 0), 2),
                        "sample_secid": sample.get("secid"),
                    }

            return result
        except Exception as exc:
            logger.warning("Ошибка расчета долгового радара: %s", exc)
            return {}

    def get_funds_rebalancing(self) -> Dict[str, Dict[str, Any]]:
        """Загружает раскрытия ребалансировок БПИФ институционалов (Т-Капитал, Ренессанс).

        Показывает, в какие акции заходят институционалы, а из каких выходят.
        """
        endpoint = f"{self.base_url}/api/view/funds.json"
        try:
            resp = self.session.get(endpoint, timeout=self.timeout)
            resp.raise_for_status()
            funds_data = resp.json().get("funds", [])

            ticker_funds_map: Dict[str, Dict[str, Any]] = {}
            for f in funds_data:
                f_ticker = f.get("ticker")
                changes = f.get("changes", [])
                for ch in changes:
                    asset = ch.get("asset", {})
                    t = asset.get("ticker")
                    if not t:
                        continue
                    w_ch = float(ch.get("weightChange") or 0.0)
                    val = float(asset.get("value") or 0.0)

                    if t not in ticker_funds_map:
                        ticker_funds_map[t] = {
                            "ticker": t,
                            "name": asset.get("name"),
                            "funds": set(),
                            "net_weight_change": 0.0,
                            "total_val_rub": 0.0,
                        }
                    ticker_funds_map[t]["funds"].add(f_ticker)
                    ticker_funds_map[t]["net_weight_change"] += w_ch
                    ticker_funds_map[t]["total_val_rub"] += val

            result: Dict[str, Dict[str, Any]] = {}
            for t, item in ticker_funds_map.items():
                net_w = round(item["net_weight_change"], 2)
                funds_list = list(item["funds"])
                if net_w >= 0.5:
                    action = "🟢 Наращивание институционалами"
                    mult = 1.03
                elif net_w <= -0.5:
                    action = "🔴 Сокращение институционалами"
                    mult = 0.97
                else:
                    action = "⚪ Удержание в портфелях"
                    mult = 1.01

                result[t] = {
                    "ticker": t,
                    "name": item.get("name"),
                    "funds": funds_list,
                    "funds_count": len(funds_list),
                    "net_weight_change": net_w,
                    "total_val_rub": item["total_val_rub"],
                    "action": action,
                    "health_mult": mult,
                }
            return result
        except Exception as exc:
            logger.warning("Ошибка анализа фондов БПИФ: %s", exc)
            return {}

    def get_ipr_summary(self) -> Dict[str, Dict[str, Any]]:
        """Загружает сводку инвестпрограмм и дивидендов сетевых компаний из формы 19."""
        endpoint = f"{self.base_url}/api/view/ipr.json"
        try:
            resp = self.session.get(endpoint, timeout=self.timeout)
            resp.raise_for_status()
            companies = resp.json().get("companies", [])
            result: Dict[str, Dict[str, Any]] = {}
            for c in companies:
                ticker = c.get("ticker")
                if not ticker:
                    continue
                ann_div = c.get("annualDividend", {})
                an = c.get("analysis", {})
                result[ticker] = {
                    "ticker": ticker,
                    "name": c.get("name"),
                    "div_status": ann_div.get("status", "—"),
                    "nearest_year": an.get("nearest", {}).get("year", 2026),
                }
            return result
        except Exception as exc:
            logger.warning("Ошибка анализа ИПР: %s", exc)
            return {}
