"""Юнит-тесты нормализации доходностей облигаций (`src/izi_mcp_client.py`)."""
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.izi_mcp_client import normalize_closed_deal_pnl  # noqa: E402


class ClosedBondPnlNormalizationTest(unittest.TestCase):
    def test_brusnika_redemption_double_principal_removed(self):
        # Реальная сделка RU000A102Y58: куплено 123 шт по 1002.8191, погашено по 1000 + купоны 17660.34
        pnl, ret = normalize_closed_deal_pnl(
            open_p=1002.8191,
            close_p=1000.0,
            cnt=123.0,
            dohod=17660.34,
            raw_yield=140313.59,
            raw_yield_pct=113.76,
        )
        self.assertAlmostEqual(pnl, 17313.59, places=1)
        self.assertAlmostEqual(ret, 14.04, places=1)

    def test_vtb_and_kamaz_amortization_double_principal_removed(self):
        pnl_vtb, ret_vtb = normalize_closed_deal_pnl(
            open_p=1000.8653, close_p=1000.0, cnt=19.0, dohod=1629.44,
            raw_yield=20613.0, raw_yield_pct=108.4,
        )
        self.assertAlmostEqual(pnl_vtb, 1613.0, places=1)
        self.assertAlmostEqual(ret_vtb, 8.48, places=1)

        pnl_kamaz, ret_kamaz = normalize_closed_deal_pnl(
            open_p=405.559, close_p=400.0, cnt=21.0, dohod=183.33,
            raw_yield=8466.59, raw_yield_pct=99.41,
        )
        self.assertAlmostEqual(pnl_kamaz, 66.59, places=1)
        self.assertAlmostEqual(ret_kamaz, 0.78, places=1)

    def test_legitimate_100pct_stock_gain_untouched(self):
        # OZON действительно вырос >100%: raw_yield совпадает с (close - open)*cnt + dohod
        pnl, ret = normalize_closed_deal_pnl(
            open_p=2295.378, close_p=4507.842, cnt=5.0, dohod=717.75,
            raw_yield=11780.07, raw_yield_pct=102.64,
        )
        self.assertEqual(pnl, 11780.07)
        self.assertEqual(ret, 102.64)


if __name__ == "__main__":
    unittest.main()
