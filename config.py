"""Загрузка и проверка настроек ассистента из config.json.

Все названия программ, сайтов и пути хранятся в config.json,
чтобы их можно было менять без правки кода. При загрузке конфиг
проверяется: если что-то не так, ConfigError объясняет, что именно и где.
"""

import json
from pathlib import Path

CONFIG_PATH = Path(__file__).with_name("config.json")

NUMBER = (int, float)
# Необязательные настройки и их допустимые типы (bool проверяется отдельно —
# в Python True считается числом)
OPTIONAL = {
    "assistant_name": str,
    "music_program": str,
    "music_app_id": str,
    "voice_model": str,
    "wake_words": list,
    "command_timeout": NUMBER,
    "max_command_words": int,
    "volume_step_presses": int,
    "sprite_scale": NUMBER,
    "raw_microphone": bool,
    "debug_speech_log": bool,
    "search_folders": list,
    "search_depth": int,
}


class ConfigError(Exception):
    """Ошибка в config.json — текст можно показать пользователю как есть."""


def load_config(path: Path = CONFIG_PATH) -> dict:
    """Читает и проверяет JSON-конфиг."""
    try:
        # utf-8-sig: Блокнот и PowerShell часто добавляют в начало файла метку BOM
        with open(path, encoding="utf-8-sig") as f:
            config = json.load(f)
    except FileNotFoundError:
        raise ConfigError(f"Не найден файл настроек {path}") from None
    except json.JSONDecodeError as e:
        raise ConfigError(f"Ошибка в {path.name}, строка {e.lineno}, столбец {e.colno}: {e.msg}") from None
    errors = validate(config)
    if errors:
        raise ConfigError(f"Ошибки в {path.name}:\n" + "\n".join(f"• {e}" for e in errors))
    return config


def _type_ok(value, expected) -> bool:
    if expected is bool:
        return isinstance(value, bool)
    return isinstance(value, expected) and not isinstance(value, bool)


def validate(config) -> list[str]:
    """Возвращает список найденных ошибок (пустой — всё в порядке)."""
    if not isinstance(config, dict):
        return ["весь файл должен быть объектом { ... }"]
    errors = []

    for key, expected in OPTIONAL.items():
        if key in config and not _type_ok(config[key], expected):
            errors.append(f"«{key}» имеет неверный тип")

    for section, field in (("programs", "target"), ("sites", "url")):
        items = config.get(section)
        if not isinstance(items, dict):
            errors.append(f"нет раздела «{section}» или он не объект {{ ... }}")
            continue
        for name, item in items.items():
            where = f"{section} → {name}"
            if not isinstance(item, dict):
                errors.append(f"{where}: должен быть объектом {{ ... }}")
                continue
            if not isinstance(item.get(field), str) or not item[field]:
                errors.append(f"{where}: нет поля «{field}»")
            aliases = item.get("aliases", [])
            if not isinstance(aliases, list) or not all(isinstance(a, str) for a in aliases):
                errors.append(f"{where}: «aliases» должен быть списком строк")
            if "process" in item and not isinstance(item["process"], str):
                errors.append(f"{where}: «process» должен быть строкой")
            if "force_close" in item and not isinstance(item["force_close"], bool):
                errors.append(f"{where}: «force_close» должен быть true или false")

    wake = config.get("wake_words")
    if isinstance(wake, list) and (not wake or not all(isinstance(w, str) and w.strip() for w in wake)):
        errors.append("«wake_words» должен быть непустым списком слов")

    music = config.get("music_program")
    if isinstance(music, str) and isinstance(config.get("programs"), dict) and music not in config["programs"]:
        errors.append(f"«music_program»: программы «{music}» нет в разделе programs")

    return errors
