"""Люся — прототип голосового ассистента.

Запуск:
  python main.py            — окно с пиксельной героиней и голосом
  python main.py --console  — старый текстовый режим в консоли
"""

import logging
import sys
from pathlib import Path

from commands import parse
from config import ConfigError, load_config
from executor import Executor


def run_console(config: dict) -> None:
    executor = Executor(config)
    name = config.get("assistant_name", "Люся")
    print(f"{name}: Слушаю. Напишите «помощь», чтобы увидеть список команд.")
    while True:
        try:
            text = input("Вы: ")
        except (EOFError, KeyboardInterrupt):
            print()
            break
        response = executor.execute(parse(text, name))
        print(f"{name}: {response.text}")
        if not response.keep_running:
            break


def show_config_error(error: ConfigError, console: bool) -> None:
    """Показывает ошибку настроек: в консоли — текстом, иначе — окошком."""
    if console:
        print(error, file=sys.stderr)
        return
    import tkinter as tk
    from tkinter import messagebox
    root = tk.Tk()
    root.withdraw()
    messagebox.showerror("Люся: ошибка в настройках", str(error))
    root.destroy()


def main() -> None:
    console = "--console" in sys.argv
    try:
        config = load_config()
    except ConfigError as e:
        show_config_error(e, console)
        sys.exit(1)
    if console:
        run_console(config)
    else:
        logs = Path(__file__).with_name("logs")
        logs.mkdir(exist_ok=True)
        logging.basicConfig(filename=logs / "voice.log", filemode="w", encoding="utf-8",
                            level=logging.INFO, format="%(asctime)s %(message)s", datefmt="%H:%M:%S")
        from gui import PetApp
        PetApp(config).run()


if __name__ == "__main__":
    main()
