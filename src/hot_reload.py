"""Горячая перезагрузка подмодулей src/* для Streamlit Cloud.

После `git pull` Cloud перезапускает только скрипт страницы, а ранее импортированные модули остаются в
`sys.modules` со старым кодом. Каждый перезагружаемый модуль хранит `_LOADED_FILE_MTIME`; если файл на диске
новее — модуль перечитывается.
"""
from __future__ import annotations

import importlib
import os


def ensure_fresh_module(mod_name: str):
    """Перечитывает модуль, если файл на диске изменился после загрузки (или метка загрузки отсутствует)."""
    mod = importlib.import_module(mod_name)
    mod_file = getattr(mod, "__file__", None)
    if mod_file and os.path.exists(mod_file):
        disk_mtime = os.path.getmtime(mod_file)
        if getattr(mod, "_LOADED_FILE_MTIME", None) != disk_mtime:
            mod = importlib.reload(mod)
            setattr(mod, "_LOADED_FILE_MTIME", disk_mtime)
    return mod
