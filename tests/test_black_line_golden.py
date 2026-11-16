"""Золотой регрессионный тест Чёрной линии.

Входные данные ЗАМОРОЖЕНЫ (не читаются из fundamentals_cache.csv, который обновляется ежедневно),
поэтому тест падает только при изменении формул в src/black_line.py.

Если изменение модели намеренное — пересчитайте ожидаемые значения и обновите GOLDEN в этом файле
(в коммите укажите, какие тикеры и почему сдвинулись).

Запуск:  .venv/bin/python -m unittest discover -s tests -v
"""
import math
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.black_line import UPSIDE_SANITY_CAP_PCT, assess_model_consistency, calculate_black_line_valuation  # noqa: E402

KEY_RATE = 14.0
USD_RATE = 82.0
REL_TOL = 0.005  # допуск 0.5% на округления

GOLDEN = {
    'SNGS': dict(price=17.45, inputs={'pe': 0.72, 'pb': 0.13, 'roe': 18.7, 'debt_ebitda': -9.39, 'rev_growth': 0.0, 'div_rub': 0.85, 'fcf_yield': 99.4}, bond_ytm=None, fx=None, expected=13.26),
    'GAZP': dict(price=115.22, inputs={'pe': 1.9, 'pb': 0.15, 'roe': 7.7, 'debt_ebitda': 1.82, 'rev_growth': 3.19, 'div_rub': 0.0, 'fcf_yield': -10.3}, bond_ytm=18.62, fx=None, expected=85.92),
    'ROSN': dict(price=352.4, inputs={'pe': 15.1, 'pb': 0.4, 'roe': 2.7, 'debt_ebitda': 0.0, 'rev_growth': 0.32, 'div_rub': 13.83, 'fcf_yield': 19.2}, bond_ytm=15.21, fx=['CNY', 'USD'], expected=431.49),
    'LKOH': dict(price=5965.0, inputs={'pe': 9.53, 'pb': 1.17, 'roe': 12.0, 'debt_ebitda': -0.29, 'rev_growth': 4.01, 'div_rub': 813.0, 'fcf_yield': 19.5}, bond_ytm=7.36, fx=['USD'], expected=7363.38),
    'TATN': dict(price=586.5, inputs={'pe': 5.17, 'pb': 1.0, 'roe': 19.0, 'debt_ebitda': -0.3, 'rev_growth': 0.22, 'div_rub': 52.62, 'fcf_yield': 17.3}, bond_ytm=None, fx=None, expected=786.69),
    'SBER': dict(price=295.53, inputs={'pe': 3.47, 'pb': None, 'roe': 23.5, 'debt_ebitda': 1.0, 'rev_growth': 6.32, 'div_rub': 37.64, 'fcf_yield': None}, bond_ytm=18.1, fx=['CNY'], expected=482.29),
    'T': dict(price=288.98, inputs={'pe': 4.97, 'pb': None, 'roe': 29.1, 'debt_ebitda': 1.0, 'rev_growth': 42.56, 'div_rub': 14.9, 'fcf_yield': None}, bond_ytm=None, fx=None, expected=583.98),
    'MGNT': dict(price=2040.5, inputs={'pe': -5.12, 'pb': -11.8, 'roe': -30.7, 'debt_ebitda': 2.86, 'rev_growth': 5.63, 'div_rub': 412.13, 'fcf_yield': -42.6}, bond_ytm=16.01, fx=None, expected=1469.16),
    'BELU': dict(price=312.4, inputs={'pe': 9.06, 'pb': 5.25, 'roe': 18.3, 'debt_ebitda': 1.44, 'rev_growth': 3.48, 'div_rub': 10.0, 'fcf_yield': 2.9}, bond_ytm=None, fx=None, expected=210.0),
    'AFKS': dict(price=8.9, inputs={'pe': -0.53, 'pb': -0.16, 'roe': 79.4, 'debt_ebitda': 3.46, 'rev_growth': 1.73, 'div_rub': 0.0, 'fcf_yield': -387.2}, bond_ytm=26.69, fx=None, expected=0.67),
    'NLMK': dict(price=75.14, inputs={'pe': 11.7, 'pb': 0.52, 'roe': 4.3, 'debt_ebitda': -0.28, 'rev_growth': -6.13, 'div_rub': 0.0, 'fcf_yield': 4.0}, bond_ytm=None, fx=None, expected=215.91),
    'CHMF': dict(price=700.0, inputs={'pe': 382.6, 'pb': 1.14, 'roe': 0.3, 'debt_ebitda': 0.47, 'rev_growth': -7.7, 'div_rub': 0.0, 'fcf_yield': -6.2}, bond_ytm=15.5, fx=None, expected=917.49),
    'POSI': dict(price=1293.6, inputs={'pe': 7.65, 'pb': -10.7, 'roe': 56.2, 'debt_ebitda': 0.79, 'rev_growth': 16.83, 'div_rub': 28.08, 'fcf_yield': 11.4}, bond_ytm=None, fx=None, expected=2703.96),
    'MTSS': dict(price=183.7, inputs={'pe': 6.78, 'pb': -1.61, 'roe': 1313.1, 'debt_ebitda': 1.55, 'rev_growth': 5.44, 'div_rub': 35.0, 'fcf_yield': 10.5}, bond_ytm=17.36, fx=None, expected=230.3),
    'IRAO': dict(price=2.837, inputs={'pe': 2.57, 'pb': 0.27, 'roe': 9.9, 'debt_ebitda': -1.94, 'rev_growth': 7.67, 'div_rub': 0.3214, 'fcf_yield': -20.9}, bond_ytm=None, fx=None, expected=4.64),
    'PLZL': dict(price=1077.6, inputs={'pe': 7.28, 'pb': 5.84, 'roe': 80.3, 'debt_ebitda': 3.11, 'rev_growth': 6.02, 'div_rub': 121.85, 'fcf_yield': 4.3}, bond_ytm=16.23, fx=['CNY', 'USD'], expected=1554.23),
    'MDMG': dict(price=1295.6, inputs={'pe': 8.82, 'pb': 3.59, 'roe': 28.8, 'debt_ebitda': 0.41, 'rev_growth': 12.64, 'div_rub': 85.0, 'fcf_yield': 9.5}, bond_ytm=None, fx=None, expected=1258.3),
    'NMTP': dict(price=7.045, inputs={'pe': 3.68, 'pb': 0.81, 'roe': 18.5, 'debt_ebitda': -0.6, 'rev_growth': -6.14, 'div_rub': 1.145, 'fcf_yield': 11.8}, bond_ytm=None, fx=None, expected=11.82),
    'TRNFP': dict(price=1077.0, inputs={'pe': 4.13, 'pb': 0.32, 'roe': 7.6, 'debt_ebitda': -0.54, 'rev_growth': 1.46, 'div_rub': 204.17, 'fcf_yield': 30.2}, bond_ytm=None, fx=None, expected=1839.79),
}


class BlackLineGoldenTest(unittest.TestCase):
    def test_fair_price_unchanged(self):
        drift = []
        for ticker, c in GOLDEN.items():
            res = calculate_black_line_valuation(
                ticker=ticker, price=c["price"], key_rate=KEY_RATE, usd_rate=USD_RATE,
                bond_ytm=c["bond_ytm"], fx_debt_currencies=c["fx"], **c["inputs"],
            )
            if not math.isclose(res["fair_price"], c["expected"], rel_tol=REL_TOL, abs_tol=0.02):
                drift.append(f"{ticker}: было {c['expected']}, стало {res['fair_price']} ({res['model_name']})")
        self.assertFalse(drift, "Чёрная линия сдвинулась:\n" + "\n".join(drift))

    def test_sngs_stays_discounted(self):
        """SNGS не должен снова получить фантомный апсайд (было +515% при 0.8x BV)."""
        c = GOLDEN["SNGS"]
        res = calculate_black_line_valuation(
            ticker="SNGS", price=c["price"], key_rate=KEY_RATE, usd_rate=USD_RATE, **c["inputs"])
        self.assertLess(res["upside_pct"], 10.0)


class ModelConsistencyTest(unittest.TestCase):
    def code(self, health, mos):
        return assess_model_consistency(health, mos)["code"]

    def test_ok(self):
        self.assertEqual(self.code(2.0, 30.0), "OK")

    def test_suspect_upside(self):
        self.assertEqual(self.code(2.0, UPSIDE_SANITY_CAP_PCT + 1), "SUSPECT_UPSIDE")

    def test_strong_health_vs_overvalued(self):
        self.assertEqual(self.code(2.16, -71.6), "HEALTH_VS_MOS")  # случай CNRU

    def test_weak_health_big_upside(self):
        self.assertEqual(self.code(0.22, 60.0), "WEAK_HEALTH_BIG_UPSIDE")

    def test_nan_and_none(self):
        self.assertEqual(self.code(float("nan"), 10.0), "NO_DATA")
        self.assertEqual(self.code(1.0, None), "NO_DATA")


if __name__ == "__main__":
    unittest.main()
