"""Горячая перезагрузка подмодулей src/* для Streamlit Cloud.

После `git pull` Cloud перезапускает только скрипт страницы, а ранее импортированные модули остаются в
`sys.modules` со старым кодом. Каждый перезагружаемый модуль хранит `_LOADED_FILE_MTIME`; если файл на диске
новее — модуль перечитывается.

Синхронизировано блокировкой `_RELOAD_LOCK` и повтором при `KeyError`: в Streamlit Cloud несколько сессий
могут параллельно вызывать `LocalSourcesWatcher.flush_pending_evictions()`, вычищая `sys.modules` прямо
внутри `importlib._load_unlocked`.
"""
from __future__ import annotations

import importlib
import os
import sys
import threading
import time

_RELOAD_LOCK = threading.RLock()


def ensure_fresh_module(mod_name: str):
    """Потокобезопасно перечитывает модуль, если файл на диске изменился после загрузки."""
    with _RELOAD_LOCK:
        for attempt in range(3):
            try:
                mod = importlib.import_module(mod_name)
                mod_file = getattr(mod, "__file__", None)
                if mod_file and os.path.exists(mod_file):
                    disk_mtime = os.path.getmtime(mod_file)
                    if getattr(mod, "_LOADED_FILE_MTIME", None) != disk_mtime:
                        mod = importlib.reload(mod)
                        setattr(mod, "_LOADED_FILE_MTIME", disk_mtime)
                return mod
            except KeyError:
                if attempt == 2:
                    raise
                sys.modules.pop(mod_name, None)
                importlib.invalidate_caches()
                time.sleep(0.05)
