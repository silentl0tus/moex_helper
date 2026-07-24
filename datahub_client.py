import os
from typing import Optional

import requests


class DataHubClient:
    def __init__(self, base_url: Optional[str] = None, timeout: int = 10):
        self.base_url = (base_url or os.getenv("DATAHUB_BASE_URL", "http://127.0.0.1:5000")).rstrip("/")
        self.timeout = timeout

    def get_fundamentals(self, ticker: str):
        """Try to retrieve a company-like fundamentals payload from a DataHub API instance.

        This is intentionally tolerant: the endpoint may be absent, protected, or
        return a different schema. In that case we return an empty dict so the UI
        can degrade gracefully.
        """
        if not ticker:
            return {}

        endpoints = [
            f"{self.base_url}/empresa/{ticker}",
            f"{self.base_url}/report/{ticker}",
            f"{self.base_url}/datasets",
        ]

        for endpoint in endpoints:
            try:
                response = requests.get(endpoint, timeout=self.timeout)
                if response.ok:
                    payload = response.json()
                    if isinstance(payload, dict):
                        return payload
            except Exception:
                continue

        return {}
