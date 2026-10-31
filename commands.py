"""Разбор текста команды: превращает фразу в намерение (intent) и аргумент.

Здесь только понимание того, ЧТО хочет пользователь.
Само действие выполняет executor.py.
На этапе 4 этот модуль можно будет заменить разбором через Claude API,
сохранив тот же формат Command.
"""

import re
from dataclasses import dataclass

# Возможные намерения
OPEN = "open"      # открыть программу, сайт или файл
CLOSE = "close"    # закрыть программу
MUSIC = "music"    # включить музыку (запустить Яндекс.Музыку)
MEDIA = "media"    # управление треком: play / pause / next / prev
VOLUME = "volume"  # громкость: up / down / mute
EXIT = "exit"      # выключить ассистента
HELP = "help"      # показать список команд
UNKNOWN = "unknown"

# Слова, с которых начинаются команды «открыть» и «закрыть»
OPEN_WORDS = ("открой", "запусти", "открыть", "запустить")
CLOSE_WORDS = ("закрой", "закрыть", "заверши", "выруби")

# Фразы, которые сравниваются с нормализованным текстом целиком
MUSIC_PHRASES = ("включи музыку", "поставь музыку", "запусти музыку", "врубай музыку", "музыку")
EXIT_PHRASES = ("выключи ассистента", "выключись", "отключись", "выход", "пока", "до свидания")
HELP_PHRASES = ("помощь", "что ты умеешь", "команды", "help")

# Кусочки слов → (намерение, аргумент). Достаточно, чтобы кусочек встретился
# в фразе: «сделай погромче» содержит «громч». Правила проверяются по порядку,
# поэтому «сними с паузы» (play) стоит раньше, чем «пауз» (pause).
KEYWORD_RULES = [
    (("без звука", "выключи звук", "включи звук", "мьют", "замьють"), VOLUME, "mute"),
    (("громч", "прибав", "увелич"), VOLUME, "up"),
    (("тиш", "убав", "уменьш"), VOLUME, "down"),
    (("продолж", "играй", "плей", "сними с паузы"), MEDIA, "play"),
    (("пауз", "останови", "стоп", "выключи музык"), MEDIA, "pause"),
    (("следующ", "дальше", "переключ", "скип", "пропуст", "некст"), MEDIA, "next"),
    (("предыдущ", "назад", "прошл"), MEDIA, "prev"),
]


@dataclass
class Command:
    intent: str
    argument: str = ""


def normalize(text: str) -> str:
    """Приводит фразу к единому виду: нижний регистр, ё→е, без лишней пунктуации."""
    text = text.lower().replace("ё", "е")
    # Точки и слэши оставляем: они нужны в именах файлов и путях
    text = re.sub(r"[,!?;«»\"]", " ", text)
    return " ".join(text.split())


def parse(text: str, assistant_name: str = "Люся") -> Command:
    """Определяет, какую команду ввёл пользователь."""
    text = normalize(text)

    # Обращение по имени необязательно: «Люся, открой ютуб» == «открой ютуб».
    name = normalize(assistant_name)
    if text.startswith(name):
        text = text[len(name):].strip()

    if not text:
        return Command(UNKNOWN)
    if text in EXIT_PHRASES or any(p in text for p in EXIT_PHRASES[:3]):
        return Command(EXIT)
    if text in HELP_PHRASES:
        return Command(HELP)

    # Глагол ищем не только первым словом: распознавание иногда слышит имя
    # как другое слово («клаву открой браузер»), и оно оказывается впереди
    words = text.split()
    for i, word in enumerate(words[:-1]):
        if word in OPEN_WORDS:
            return Command(OPEN, " ".join(words[i + 1:]))
        if word in CLOSE_WORDS:
            return Command(CLOSE, " ".join(words[i + 1:]))

    if text in MUSIC_PHRASES or any(p in text for p in MUSIC_PHRASES[:-1]):
        return Command(MUSIC)

    for keywords, intent, argument in KEYWORD_RULES:
        if any(k in text for k in keywords):
            return Command(intent, argument)

    return Command(UNKNOWN, text)
