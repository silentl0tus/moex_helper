"""Юнит-тесты устойчивости hot-reload к гонке Streamlit (`KeyError` при выгрузке sys.modules)."""
import importlib
import os
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.hot_reload import ensure_fresh_module  # noqa: E402


class HotReloadRaceTest(unittest.TestCase):
    def test_recovers_from_keyerror_during_watcher_eviction(self):
        real_import = importlib.import_module
        calls = {"n": 0}

        def flaky_import(name, package=None):
            calls["n"] += 1
            if calls["n"] == 1:
                raise KeyError("src.portfolio_importer")
            return real_import(name, package)

        with patch("src.hot_reload.importlib.import_module", side_effect=flaky_import):
            mod = ensure_fresh_module("src.market_snapshot")

        self.assertEqual(calls["n"], 2)
        self.assertEqual(mod.__name__, "src.market_snapshot")


if __name__ == "__main__":
    unittest.main()
