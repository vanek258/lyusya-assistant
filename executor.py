"""Выполнение команд: запуск и закрытие программ, сайты, файлы, музыка, громкость."""

import os
import time
import webbrowser
from dataclasses import dataclass
from pathlib import Path

import commands
import media
import system
from commands import Command

HELP_TEXT = (
    "Скажи «Люся» и команду: открой/закрой браузер, дискорд; открой ютуб, твич; "
    "включи музыку, пауза, играй, следующий, предыдущий; громче, тише, "
    "выключи звук; выключи ассистента."
)

MEDIA_TEXTS = {"play": "Играю.", "pause": "Пауза.", "next": "Следующий трек.", "prev": "Предыдущий трек."}
VOLUME_TEXTS = {"up": "Громче.", "down": "Тише.", "mute": "Звук: вкл/выкл."}


@dataclass
class Response:
    """Ответ ассистента.

    effect — подсказка для анимации героини, что именно произошло:
    launch, close, music_launch, music_close, music_on, music_off,
    vol_up, vol_down, mute, help, exit.
    """
    text: str
    ok: bool = True
    keep_running: bool = True
    effect: str = ""


class Executor:
    def __init__(self, config: dict):
        self.config = config
        self.music_key = config.get("music_program", "")
        # Словари «алиас → запись из конфига», чтобы искать по любому названию
        self.program_aliases = self._build_aliases(config.get("programs", {}))
        self.site_aliases = self._build_aliases(config.get("sites", {}))

    @staticmethod
    def _build_aliases(section: dict) -> dict:
        """Собирает все алиасы раздела конфига в один словарь."""
        aliases = {}
        for key, item in section.items():
            item = {**item, "key": key}
            aliases[key.lower()] = item
            for alias in item.get("aliases", []):
                aliases[commands.normalize(alias)] = item
        return aliases

    def execute(self, cmd: Command) -> Response:
        if cmd.intent == commands.EXIT:
            return Response("Пока-пока! Выключаюсь.", keep_running=False, effect="exit")
        if cmd.intent == commands.HELP:
            return Response(HELP_TEXT, effect="help")
        if cmd.intent == commands.OPEN:
            return self.open(cmd.argument)
        if cmd.intent == commands.CLOSE:
            return self.close(cmd.argument)
        if cmd.intent == commands.MUSIC:
            return self._media_safely(self.play_music)
        if cmd.intent == commands.MEDIA:
            return self._media_safely(self.media, cmd.argument)
        if cmd.intent == commands.VOLUME:
            return self.volume(cmd.argument)
        return Response("Не поняла… Скажи «помощь».", ok=False)

    # --- Действия -----------------------------------------------------------

    def open(self, name: str) -> Response:
        """Ищет, что открыть: сайт → программа из конфига → путь → файл в папках поиска."""
        if name in self.site_aliases:
            webbrowser.open(self.site_aliases[name]["url"])
            return Response(f"Открываю {name}.", effect="launch")

        if name in self.program_aliases:
            item = self.program_aliases[name]
            effect = "music_launch" if item["key"] == self.music_key else "launch"
            return self._start(item["target"], f"Запускаю {name}.", effect)

        # Пользователь мог ввести полный путь
        path = Path(name).expanduser()
        if path.exists():
            return self._start(str(path), f"Открываю {path.name}.")

        found = self._find_file(name)
        if found:
            return self._start(str(found), f"Открываю {found.name}.")

        return Response(f"Не нашла «{name}». Добавь его в config.json.", ok=False)

    def close(self, name: str) -> Response:
        item = self.program_aliases.get(name)
        if not item:
            return Response(f"Не знаю программу «{name}».", ok=False)
        process = item.get("process")
        if not process:
            return Response(f"Не знаю, как закрыть «{name}»: нет поля process в config.json.", ok=False)
        if not system.is_running(process):
            return Response(f"{name.capitalize()} и так закрыт.")
        effect = "music_close" if item["key"] == self.music_key else "close"

        if item.get("force_close", False):
            # Явно разрешено в config.json (программа прячется в трей по крестику)
            system.kill_process(process)
            return Response(f"Закрываю {name}.", effect=effect)

        windows = system.main_windows(process)
        if not windows:
            # Процесс есть, но окон нет — это фоновая часть программы, её не трогаем
            return Response(f"У «{name}» нет открытых окон — закрывать нечего.", ok=False)
        system.close_windows(windows)
        return Response(f"Закрываю {name}. Если что-то не сохранено, программа спросит.", effect=effect)

    def play_music(self) -> Response:
        """Включает именно Яндекс.Музыку. Если она закрыта — запускает и ждёт, пока загрузится."""
        item = self.config.get("programs", {}).get(self.music_key)
        if not item:
            return Response("Музыкальная программа не указана в config.json (music_program).", ok=False)
        if not media.AVAILABLE:  # запасной путь — медиаклавиша (достаётся «текущему» плееру)
            system.press_key(system.MEDIA_KEYS["play"])
            return Response("Включаю музыку.", effect="music_on")

        app_id = self.config.get("music_app_id", "Yandex.Music")
        if media.play(app_id):
            return Response("Включаю музыку.", effect="music_on")
        launched = self._start(item["target"], "", "music_launch")
        if not launched.ok:
            return launched
        for _ in range(40):  # до 20 секунд ждём, пока плеер появится в системе
            time.sleep(0.5)
            if media.play(app_id):
                return Response("Включаю Яндекс.Музыку.", effect="music_on")
        return Response("Открыла Яндекс.Музыку, но она пока не отвечает. Скажи «играй» чуть позже.",
                        effect="music_launch")

    def media(self, action: str) -> Response:
        if not media.AVAILABLE:
            system.press_key(system.MEDIA_KEYS[action])
            return Response(MEDIA_TEXTS[action], effect="music_off" if action == "pause" else "music_on")

        app_id = self.config.get("music_app_id", "Yandex.Music")
        if action == "pause":
            # Пауза — всему, что играет (музыке, ролику в браузере). Пока она слушала
            # команду, музыка уже могла встать на паузу — ответ всё равно «Пауза»
            media.pause_playing()
            return Response(MEDIA_TEXTS[action], effect="music_off")
        found = media.play(app_id) if action == "play" else media.skip(app_id, forward=action == "next")
        if not found:
            return Response("Яндекс.Музыка не запущена. Скажи «включи музыку».", ok=False)
        return Response(MEDIA_TEXTS[action], effect="music_on")

    def volume(self, action: str) -> Response:
        # Одно нажатие клавиши громкости в Windows = 2%
        times = 1 if action == "mute" else self.config.get("volume_step_presses", 5)
        system.press_key(system.VOLUME_KEYS[action], times)
        return Response(VOLUME_TEXTS[action], effect=f"vol_{action}" if action != "mute" else "mute")

    # --- Вспомогательное ----------------------------------------------------

    @staticmethod
    def _media_safely(action, *args) -> Response:
        """Выполняет музыкальную команду и честно сообщает, если плеер не ответил."""
        try:
            return action(*args)
        except media.MediaTimeout:
            return Response("Плеер не ответил вовремя — не знаю, сработало ли. Проверь сам.", ok=False)
        except OSError as e:  # ошибки WinRT приходят как OSError
            return Response(f"Не получилось управлять плеером: {e}", ok=False)

    @staticmethod
    def _start(target: str, success_message: str, effect: str = "launch") -> Response:
        """Запускает программу/файл средствами Windows (как двойной клик)."""
        try:
            os.startfile(target)
            return Response(success_message, effect=effect)
        except OSError as e:
            return Response(f"Не удалось открыть: {e}", ok=False)

    def _find_file(self, name: str) -> Path | None:
        """Ищет файл или папку по имени в папках из search_folders.

        Сначала ищется точное совпадение (с расширением или без),
        если его нет — первое совпадение по части имени.
        """
        max_depth = self.config.get("search_depth", 2)
        partial = None
        for folder in self.config.get("search_folders", []):
            root = Path(folder).expanduser()
            if not root.is_dir():
                continue
            for path in self._walk(root, max_depth):
                full, stem = path.name.lower(), path.stem.lower()
                if name in (full, stem):
                    return path
                if partial is None and name in full:
                    partial = path
        return partial

    @staticmethod
    def _walk(root: Path, max_depth: int):
        """Обходит папку не глубже max_depth уровней (чтобы поиск был быстрым)."""
        root_depth = len(root.parts)
        for dirpath, dirnames, filenames in os.walk(root):
            current = Path(dirpath)
            if len(current.parts) - root_depth >= max_depth:
                dirnames.clear()  # глубже не идём
            for entry in dirnames + filenames:
                yield current / entry
