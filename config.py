"""Загрузка настроек ассистента из config.json.

Все названия программ, сайтов и пути хранятся в config.json,
чтобы их можно было менять без правки кода.
"""

import json
from pathlib import Path

CONFIG_PATH = Path(__file__).with_name("config.json")


def load_config(path: Path = CONFIG_PATH) -> dict:
    """Читает JSON-конфиг и возвращает его как словарь."""
    with open(path, encoding="utf-8") as f:
        return json.load(f)
