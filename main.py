"""Люся — прототип голосового ассистента.

Запуск:
  python main.py            — окно с пиксельной героиней и голосом
  python main.py --console  — старый текстовый режим в консоли
"""

import logging
import sys
from pathlib import Path

from commands import parse
from config import load_config
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


def main() -> None:
    config = load_config()
    if "--console" in sys.argv:
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
