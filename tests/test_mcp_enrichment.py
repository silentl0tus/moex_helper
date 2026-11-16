"""Юнит-тесты обогащения мультипликаторов через Data Foundry MCP (`src/mcp_enrichment.py`).

Все тесты детерминированные, без сетевых запросов.
Запуск:  .venv/bin/python -m unittest discover -s tests -v
"""
import os
import sys
import unittest

import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.mcp_enrichment import (  # noqa: E402
    _pick_fresher_equity,
    compute_ltm_flow,
    compute_yoy_revenue_growth,
    derive_multiples_from_mcp,
    enrich_fundamentals_with_mcp,
)


class LtmAndEquityResolutionTest(unittest.TestCase):
    def test_ltm_from_partial_year(self):
        series = {"2025-FY": 1705.9e9, "2025-9M": 1307.3e9, "2026-9M": 1529.9e9}
        val, lbl = compute_ltm_flow(series)
        self.assertAlmostEqual(val, 1928.5e9)
        self.assertEqual(lbl, "LTM 2026-9M")

    def test_prefers_full_year_over_partial_same_year(self):
        series = {"2024-FY": 100.0, "2024-9M": 70.0, "2025-9M": 90.0, "2025-FY": 130.0}
        val, lbl = compute_ltm_flow(series)
        self.assertEqual(val, 130.0)
        self.assertEqual(lbl, "2025-FY")

    def test_vtbr_stale_ltm_guard_never_falls_back_five_years(self):
        # Реальный случай VTBR: есть 2026-9M и 2025-9M, нет 2025-FY; старый 2021-LTM брать нельзя
        vtbr_ni = {
            "2020-FY": 75.3e9, "2020-9M": 59.1e9, "2021-9M": 257.6e9,
            "2025-9M": 380.8e9, "2026-9M": 407.5e9, "2026-Q3": 182.3e9,
        }
        val, lbl = compute_ltm_flow(vtbr_ni)
        self.assertIsNone(val)
        self.assertIsNone(lbl)

    def test_four_discrete_quarters(self):
        series = {"2025-Q4": 30.0, "2026-Q1": 20.0, "2026-Q2": 25.0, "2026-Q3": 35.0}
        val, lbl = compute_ltm_flow(series)
        self.assertEqual(val, 110.0)
        self.assertEqual(lbl, "LTM 4Q до 2026-Q3")

    def test_picks_fresher_total_equity_when_attributable_stale(self):
        # Реальный случай SBER/T: equity_attributable_to_owners обрывается раньше total_equity
        raw = {
            "fin.equity_attributable_to_owners": {"ASOF:2023-06-30": 239e9},
            "fin.total_equity": {"ASOF:2026-09-30": 915.9e9},
        }
        val, pk = _pick_fresher_equity(raw, prefer_attributable_equity=True)
        self.assertEqual(val, 915.9e9)
        self.assertEqual(pk, "ASOF:2026-09-30")

    def test_yoy_revenue_growth(self):
        rev = {"2024-9M": 100.0, "2024-FY": 140.0, "2025-9M": 120.0, "2025-FY": 168.0, "2026-9M": 150.0}
        self.assertEqual(compute_yoy_revenue_growth(rev), 25.0)


class DeriveAndEnrichTest(unittest.TestCase):
    def test_rejects_sfin_scale_anomaly(self):
        # В MCP SFIN 2025-FY имел масштабную ошибку x1000 (20.8 трлн вместо млрд)
        raw = {
            "fin.total_equity": {"ASOF:2026-06-30": 53.5e9},
            "fin.net_income": {"2025-FY": 20.84e12, "2025-Q1": 3.34e9, "2026-Q1": 0.50e9},
        }
        d = derive_multiples_from_mcp(raw, total_cap=30e9, reference_year=2026)
        self.assertEqual(d["P_BV"], 0.56)
        self.assertIsNone(d["P_E"])
        self.assertIsNone(d["ROE_%"])

    def test_bank_atomic_triple_vs_consistent_fallback(self):
        df = pd.DataFrame([
            {"ticker": "SBER", "ROE_%": 23.5, "P_E": 3.47, "P_BV": float("nan"), "Debt_EBITDA": 1.0, "Rev_Growth_%": 6.3, "FCF_Yield_%": float("nan"), "Div_RUB": 37.64},
            {"ticker": "VTBR", "ROE_%": 24.8, "P_E": 1.56, "P_BV": float("nan"), "Debt_EBITDA": float("nan"), "Rev_Growth_%": 24.5, "FCF_Yield_%": float("nan"), "Div_RUB": 9.71},
            {"ticker": "LKOH", "ROE_%": 12.0, "P_E": 9.53, "P_BV": 1.17, "Debt_EBITDA": -0.29, "Rev_Growth_%": float("nan"), "FCF_Yield_%": 19.5, "Div_RUB": 813.0},
        ])
        cap_map = {
            "SBER": {"total_cap": 6675e9},
            "VTBR": {"total_cap": 785.7e9},
            "LKOH": {"total_cap": 4100e9},
        }
        mcp_by_ticker = {
            "SBER": {
                "fin.total_equity": {"ASOF:2026-09-30": 9000.8e9},
                "fin.net_income": {"2025-FY": 1705.9e9, "2025-9M": 1307.3e9, "2026-9M": 1529.9e9},
            },
            "VTBR": {
                # LTM 2021-9M отсечётся фильтром свежести, останется только total_equity -> фолбэк P_E*ROE=0.39
                "fin.total_equity": {"ASOF:2026-09-30": 3013.4e9},
                "fin.net_income": {"2020-FY": 75.3e9, "2020-9M": 59.1e9, "2021-9M": 257.6e9, "2026-9M": 407.5e9},
            },
            "LKOH": {
                "fin.revenue": {"2025-FY": 8000e9, "2025-H1": 3800e9, "2026-H1": 4180e9},
                "fin.total_equity": {"ASOF:2026-06-30": 6000e9},
            },
        }
        out = enrich_fundamentals_with_mcp(
            df,
            bank_tickers={"SBER", "VTBR"},
            cap_map=cap_map,
            mcp_by_ticker=mcp_by_ticker,
            reference_year=2026,
        ).set_index("ticker")

        # SBER: согласованная тройка из MCP
        self.assertEqual(out.loc["SBER", "P_BV"], 0.74)
        self.assertEqual(out.loc["SBER", "P_E"], 3.46)
        self.assertEqual(out.loc["SBER", "ROE_%"], 21.4)

        # VTBR: сохранил свежие P_E/ROE smart-lab, Debt=1.0 и согласованный P/BV=0.39 (не 0.26 со старой ROE!)
        self.assertEqual(out.loc["VTBR", "ROE_%"], 24.8)
        self.assertEqual(out.loc["VTBR", "P_E"], 1.56)
        self.assertEqual(out.loc["VTBR", "P_BV"], 0.39)
        self.assertEqual(out.loc["VTBR", "Debt_EBITDA"], 1.0)

        # LKOH (небанк): заполнена только дырка Rev_Growth_%, остальные данные smart-lab не тронуты
        self.assertEqual(out.loc["LKOH", "P_BV"], 1.17)
        self.assertEqual(out.loc["LKOH", "Rev_Growth_%"], 10.0)


if __name__ == "__main__":
    unittest.main()
