"""Шлюз данных к морской аналитической платформе TankerMap (https://tankermap.com).

Предоставляет:
1. Живой трекинг танкерного флота РФ (порты отгрузки Балтики, Черного моря, Дальнего Востока, Арктики).
2. Загрузка и объемы экспортного флота (Crude Oil, Products, LNG, дедвейт DWT).
3. Мониторинг узких проливов (Chokepoints: Суэц, Ормуз, Малакка).
4. Анализ санкционного / теневого флота (Shadow fleet).
5. Лента новостей морских перевозок и геополитических рисков.
"""

import logging
from typing import Any, Dict, List, Optional
import requests

logger = logging.getLogger(__name__)

TANKERMAP_BASE_URL = "https://tankermap.com"

# Ключевые российские нефтяные порты и терминалы
RU_PORT_KEYWORDS = {
    "Балтика (Urals)": ["UST-LUGA", "PRIMORSK", "ST PETERSBURG", "VYSOTSK"],
    "Черное море (Urals / КТК)": ["NOVOROSSIYSK", "TUAPSE", "TAMAN", "KAVKAZ"],
    "Дальний Восток (ВСТО / ESPO)": ["KOZMINO", "DE-KASTRI", "PRIGORODNOYE", "VLADIVOSTOK"],
    "Арктика (Варандей / СПГ)": ["MURMANSK", "SABETTA", "UTRENNIY", "VARANDEY", "ARCTIC"],
}


class TankerMapGateway:
    def __init__(self, timeout: int = 15):
        self.base_url = TANKERMAP_BASE_URL
        self.timeout = timeout
        self.session = requests.Session()
        self.session.headers.update({
            "User-Agent": "MOEX-Helper-RoboAdvisor/2.0 (Maritime Analytics Integration)",
            "Accept": "application/json",
        })

    def get_russian_export_analytics(self) -> Dict[str, Any]:
        """Загружает базу live-танкеров и агрегирует статистику по российскому морскому экспорту нефти и нефтепродуктов."""
        endpoint = f"{self.base_url}/api/vessels/live"
        try:
            resp = self.session.get(endpoint, timeout=self.timeout)
            resp.raise_for_status()
            vessels = resp.json()
            if not isinstance(vessels, list):
                vessels = vessels.get("vessels", [])

            ru_vessels: List[Dict[str, Any]] = []
            sanctioned_count = 0
            loaded_crude_dwt = 0
            loaded_prod_dwt = 0
            loaded_lng_dwt = 0

            port_stats: Dict[str, int] = {k: 0 for k in RU_PORT_KEYWORDS}

            for v in vessels:
                dest = str(v.get("destination") or "").upper()
                flag = str(v.get("flag") or "").upper()
                v_type = str(v.get("vessel_type") or "").lower()
                cargo = str(v.get("cargo_state") or "").lower()
                dwt = int(v.get("deadweight") or 0)
                is_sanctioned = v.get("sanctions_status") == "SANCTIONED"

                if is_sanctioned:
                    sanctioned_count += 1

                # Определение принадлежности к экспорту РФ
                matched_region = None
                for region, kw_list in RU_PORT_KEYWORDS.items():
                    if any(kw in dest for kw in kw_list):
                        matched_region = region
                        port_stats[region] += 1
                        break

                if matched_region or flag == "RUSSIA":
                    ru_vessels.append(v)
                    if cargo == "loaded":
                        if "crude" in v_type:
                            loaded_crude_dwt += dwt
                        elif "product" in v_type or "chemical" in v_type:
                            loaded_prod_dwt += dwt
                        elif "lng" in v_type or "gas" in v_type:
                            loaded_lng_dwt += dwt

            return {
                "total_ru_vessels": len(ru_vessels),
                "total_tracked_global": len(vessels),
                "sanctioned_vessels_global": sanctioned_count,
                "loaded_crude_dwt": loaded_crude_dwt,
                "loaded_prod_dwt": loaded_prod_dwt,
                "loaded_lng_dwt": loaded_lng_dwt,
                "total_export_dwt": loaded_crude_dwt + loaded_prod_dwt + loaded_lng_dwt,
                "port_distribution": port_stats,
                "vessels_sample": ru_vessels[:25],  # первые 25 судов для детальной таблицы
            }
        except Exception as exc:
            logger.warning("Ошибка загрузки данных флота из TankerMap: %s", exc)
            return {
                "total_ru_vessels": 0,
                "total_tracked_global": 0,
                "sanctioned_vessels_global": 0,
                "loaded_crude_dwt": 0,
                "loaded_prod_dwt": 0,
                "loaded_lng_dwt": 0,
                "total_export_dwt": 0,
                "port_distribution": {},
                "vessels_sample": [],
            }

    def get_chokepoints_analytics(self) -> Dict[str, Any]:
        """Загружает статус и динамику трафика через критические проливы (Суэц, Ормуз, Малакка)."""
        endpoint = f"{self.base_url}/api/analytics/chokepoints"
        try:
            resp = self.session.get(endpoint, timeout=self.timeout)
            resp.raise_for_status()
            data = resp.json()
            return data.get("summary", {})
        except Exception as exc:
            logger.warning("Ошибка загрузки аналитики проливов TankerMap: %s", exc)
            return {}

    def get_maritime_news(self, limit: int = 15) -> List[Dict[str, Any]]:
        """Загружает актуальные новости и геополитические алерты по танкерным перевозкам."""
        endpoint = f"{self.base_url}/api/news"
        try:
            resp = self.session.get(endpoint, timeout=self.timeout)
            resp.raise_for_status()
            news_items = resp.json()
            if isinstance(news_items, list):
                return news_items[:limit]
            return []
        except Exception as exc:
            logger.warning("Ошибка загрузки новостей TankerMap: %s", exc)
            return []
