"""Тесты общих функций оценки, которыми пользуются главный экран и Мастер подбора.

Запуск:  .venv/bin/python -m unittest discover -s tests -v
"""
import math
import os
import sys
import unittest

import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.black_line import classify_debt_fx_badge, enrich_with_black_line  # noqa: E402


def _row(ticker, **kw):
    base = dict(ticker=ticker, P_E=5.0, P_BV=1.0, **{"ROE_%": 20.0}, Debt_EBITDA=0.5,
                **{"Rev_Growth_%": 5.0}, Div_RUB=10.0, **{"FCF_Yield_%": 8.0}, Health_Score=2.0)
    base.update(kw)
    return base


class DebtFxBadgeTest(unittest.TestCase):
    def badge(self, ticker="XXXX", debt=2.0, roe=10.0, fcf=1.0, ytm=None, fx=None, kr=14.0):
        return classify_debt_fx_badge(ticker, debt, roe, fcf, ytm, fx, kr)

    def test_net_cash(self):
        self.assertEqual(self.badge(debt=-0.5), "💎 Чистый кэш")

    def test_net_cash_exporter_with_fx_debt(self):
        self.assertEqual(self.badge("LKOH", debt=-0.3, fx=["USD"]), "💎 Чистый кэш (FX)")

    def test_expensive_debt_by_bond_yield(self):
        self.assertIn("Дорогой долг", self.badge(debt=2.0, ytm=29.0))

    def test_subsidized_when_roe_above_key_rate(self):
        self.assertEqual(self.badge(debt=2.0, roe=20.0, fcf=5.0), "🟢 Льготный/Фикс. долг")

    def test_fx_debt_of_domestic_business(self):
        self.assertIn("FX-долг", self.badge("GAZP", debt=1.4, roe=5.0, fcf=5.0, fx=["USD", "CNY"]))

    def test_heavy_rub_debt(self):
        self.assertEqual(self.badge(debt=2.5, roe=5.0, fcf=1.0), "⚠️ Тяжёлый долг (RUB)")

    def test_nan_inputs_do_not_crash(self):
        self.assertTrue(self.badge(debt=float("nan"), roe=float("nan"), fcf=float("nan")))


class EnrichWithBlackLineTest(unittest.TestCase):
    def test_columns_and_values(self):
        df = pd.DataFrame([_row("SBER"), _row("NOPRICE")])
        out = enrich_with_black_line(df, {"SBER": 300.0}, key_rate=14.0, usd_rate=82.0)
        for col in ("Price", "Чёрная Линия (₽)", "Margin of Safety (%)", "Доверие модели", "Долг и Валюта"):
            self.assertIn(col, out.columns)
        sber = out[out["ticker"] == "SBER"].iloc[0]
        self.assertEqual(sber["Price"], 300.0)
        self.assertGreater(sber["Чёрная Линия (₽)"], 0)

    def test_missing_price_is_not_invented(self):
        df = pd.DataFrame([_row("NOPRICE")])
        out = enrich_with_black_line(df, {}, key_rate=14.0, usd_rate=None).iloc[0]
        self.assertTrue(math.isnan(out["Price"]))
        self.assertTrue(math.isnan(out["Чёрная Линия (₽)"]))
        self.assertTrue(math.isnan(out["Margin of Safety (%)"]))
        self.assertIn("нет данных", out["Доверие модели"])

    def test_input_frame_not_mutated(self):
        df = pd.DataFrame([_row("SBER")])
        enrich_with_black_line(df, {"SBER": 300.0}, key_rate=14.0, usd_rate=82.0)
        self.assertNotIn("Price", df.columns)

    def test_matches_direct_calculation(self):
        """Колонка Чёрной линии совпадает с прямым вызовом оценки (одна и та же функция на обоих экранах)."""
        from src.black_line import calculate_black_line_valuation
        r = _row("TATN")
        out = enrich_with_black_line(pd.DataFrame([r]), {"TATN": 586.5}, key_rate=14.0, usd_rate=82.0, bonds={}, fx_issuers={})
        direct = calculate_black_line_valuation(
            ticker="TATN", price=586.5, pe=r["P_E"], pb=r["P_BV"], roe=r["ROE_%"], debt_ebitda=r["Debt_EBITDA"],
            rev_growth=r["Rev_Growth_%"], div_rub=r["Div_RUB"], key_rate=14.0, fcf_yield=r["FCF_Yield_%"],
            usd_rate=82.0, bond_ytm=None, fx_debt_currencies=None)
        self.assertAlmostEqual(out.iloc[0]["Чёрная Линия (₽)"], direct["fair_price"], places=2)


if __name__ == "__main__":
    unittest.main()
