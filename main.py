"""Люся — прототип голосового ассистента.

Запуск:
  python main.py            — окно с пиксельной героиней и голосом
  python main.py --console  — старый текстовый режим в консоли
"""

import ctypes
import logging
import sys
from pathlib import Path

from config import ConfigError, load_config


def run_console(config: dict) -> None:
    """Текстовый режим — через то же ядро, что и окно (с теми же проверками и подтверждениями)."""
    from events import TYPED, Reply, Utterance
    dialogue = build_dialogue(config)
    name = config.get("assistant_name", "Люся")
    print(f"{name}: Слушаю. Напишите «помощь», чтобы увидеть список команд.")
    try:
        while True:
            try:
                text = input("Вы: ")
            except (EOFError, KeyboardInterrupt):
                print()
                break
            if dialogue.submit(Utterance(text, source=TYPED)) is None:
                continue
            reply = dialogue.outbox.get()
            while not isinstance(reply, Reply):  # состояния («думаю») в консоли не нужны
                reply = dialogue.outbox.get()
            print(f"{name}: {reply.text}")
            if not reply.keep_running:
                break
    finally:
        dialogue.shutdown()


MUTEX_NAME = "Local\\LyusyaAssistant"
ERROR_ALREADY_EXISTS = 183


def acquire_single_instance(name: str = MUTEX_NAME):
    """Не даёт запустить вторую Люсю: иначе обе слышали бы и выполняли каждую команду.

    Возвращает дескриптор именованного мьютекса (его нужно держать до выхода)
    или None, если Люся уже запущена.
    """
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel32.CreateMutexW.restype = ctypes.c_void_p
    handle = kernel32.CreateMutexW(None, False, name)
    if handle and ctypes.get_last_error() == ERROR_ALREADY_EXISTS:
        kernel32.CloseHandle(ctypes.c_void_p(handle))
        return None
    return handle


def build_ai(config: dict):
    """ИИ-провайдеры. Пока ни одного не подключено — Gemini появится на этапе 3.

    Возвращает AIRouter или None (тогда Люся отвечает «ИИ пока не подключён»).
    """
    from ai.router import AIRouter
    providers = {}
    return AIRouter(config, providers) if providers else None


def build_dialogue(config: dict):
    """Собирает ядро: исполнитель → инструменты → маршрутизатор → ИИ → диалог."""
    from dialogue import DialogueManager
    return DialogueManager(config, ai=build_ai(config))


def show_message(title: str, text: str, console: bool) -> None:
    """Показывает сообщение: в консоли — текстом, иначе — окошком."""
    if console:
        print(text, file=sys.stderr)
        return
    import tkinter as tk
    from tkinter import messagebox
    root = tk.Tk()
    root.withdraw()
    messagebox.showerror(title, text)
    root.destroy()


def main() -> None:
    console = "--console" in sys.argv
    try:
        config = load_config()
    except ConfigError as e:
        show_message("Люся: ошибка в настройках", str(e), console)
        sys.exit(1)
    if console:
        run_console(config)
    else:
        instance = acquire_single_instance()  # держим до выхода из программы
        if instance is None:
            show_message("Люся", "Люся уже запущена — она внизу экрана.", console)
            sys.exit(0)
        logs = Path(__file__).with_name("logs")
        logs.mkdir(exist_ok=True)
        logging.basicConfig(filename=logs / "voice.log", filemode="w", encoding="utf-8",
                            level=logging.INFO, format="%(asctime)s %(message)s", datefmt="%H:%M:%S")
        from gui import PetApp
        PetApp(config, build_dialogue(config)).run()


if __name__ == "__main__":
    main()
