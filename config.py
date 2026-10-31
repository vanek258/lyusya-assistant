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


# Облачная обработка: выключена, пока пользователь сам её не включит
CLOUD_DEFAULTS = {
    "enabled": False,
    "allow_fallback": False,
    "max_words": 25,
    "min_confidence": 0.75,
    "daily_request_limit": 200,
}


def cloud_settings(config: dict) -> dict:
    """Настройки облака с подставленными значениями по умолчанию."""
    return {**CLOUD_DEFAULTS, **config.get("cloud", {})}


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

    errors += _validate_cloud(config.get("cloud"))
    errors += _validate_ai(config.get("ai"))
    errors += [f"«{path}»: ключи и пароли нельзя хранить в config.json — используй "
               f"python secret_store.py set <имя>" for path in _secret_like_keys(config)]
    return errors


CLOUD_TYPES = {
    "enabled": bool,
    "allow_fallback": bool,
    "max_words": int,
    "min_confidence": NUMBER,
    "daily_request_limit": int,
}
AI_TASKS = {"chat", "complex", "coding"}
SECRET_WORDS = ("key", "token", "secret", "password", "passwd", "ключ", "пароль", "токен")


def _validate_cloud(cloud) -> list[str]:
    if cloud is None:
        return []  # раздела нет — облако выключено (конфиг этапа 1 работает без изменений)
    if not isinstance(cloud, dict):
        return ["«cloud» должен быть объектом { ... }"]
    errors = []
    for key, value in cloud.items():
        expected = CLOUD_TYPES.get(key)
        if expected is None:
            errors.append(f"cloud → неизвестный параметр «{key}»")
        elif not _type_ok(value, expected):
            errors.append(f"cloud → «{key}» имеет неверный тип")
    if _type_ok(cloud.get("max_words"), int) and cloud["max_words"] < 1:
        errors.append("cloud → «max_words» должен быть больше нуля")
    if _type_ok(cloud.get("min_confidence"), NUMBER) and not 0 <= cloud["min_confidence"] <= 1:
        errors.append("cloud → «min_confidence» должен быть от 0 до 1")
    if _type_ok(cloud.get("daily_request_limit"), int) and cloud["daily_request_limit"] < 0:
        errors.append("cloud → «daily_request_limit» не может быть отрицательным")
    return errors


def _validate_ai(ai) -> list[str]:
    if ai is None:
        return []
    if not isinstance(ai, dict):
        return ["«ai» должен быть объектом { ... }"]
    errors = []
    providers = ai.get("providers", {})
    if not isinstance(providers, dict):
        errors.append("ai → «providers» должен быть объектом { ... }")
    else:
        for name, settings in providers.items():
            if not isinstance(settings, dict):
                errors.append(f"ai → providers → {name}: должен быть объектом {{ ... }}")
                continue
            if "model" in settings and not isinstance(settings["model"], str):
                errors.append(f"ai → providers → {name}: «model» должен быть строкой")
            timeout = settings.get("timeout", 1)
            if not _type_ok(timeout, NUMBER) or timeout <= 0:
                errors.append(f"ai → providers → {name}: «timeout» должен быть числом больше нуля")
    routing = ai.get("routing", {})
    if not isinstance(routing, dict):
        errors.append("ai → «routing» должен быть объектом { ... }")
    else:
        for task, order in routing.items():
            if task not in AI_TASKS:
                errors.append(f"ai → routing: неизвестный тип задачи «{task}» (есть: {', '.join(sorted(AI_TASKS))})")
            if not isinstance(order, list) or not all(isinstance(n, str) for n in order):
                errors.append(f"ai → routing → {task}: должен быть списком имён провайдеров")
    return errors


def _secret_like_keys(value, path: str = "", names_are_entries: bool = False):
    """Названия параметров, похожие на ключи и пароли (на любой глубине).

    В разделах programs и sites ключи словаря — это имена программ и сайтов,
    выбранные пользователем (например, «keepass»), их не проверяем.
    """
    if isinstance(value, dict):
        for key, inner in value.items():
            where = f"{path} → {key}" if path else str(key)
            if not names_are_entries and any(word in str(key).lower() for word in SECRET_WORDS):
                yield where
            entries = not path and key in ("programs", "sites")
            yield from _secret_like_keys(inner, where, names_are_entries=entries)
    elif isinstance(value, list):
        for item in value:
            yield from _secret_like_keys(item, path)
