"""Безопасное хранение API-ключей.

Ключи лежат в Диспетчере учётных данных Windows (через пакет keyring) —
не в config.json, не в коде, не в журналах и не в Git. Для автоматических
тестов ключ можно передать переменной окружения LYUSYA_<ИМЯ>, например
LYUSYA_GEMINI_API_KEY; её значение тоже никуда не записывается.

Сохранить ключ (ввод скрыт, ключ не печатается):
    python secret_store.py set gemini_api_key
Проверить, что ключ есть:
    python secret_store.py check gemini_api_key
Удалить:
    python secret_store.py delete gemini_api_key
"""

import getpass
import logging
import os
import sys

log = logging.getLogger("secrets")

SERVICE = "lyusya-assistant"  # под этим именем записи видны в Диспетчере учётных данных
ENV_PREFIX = "LYUSYA_"


class SecretStore:
    def __init__(self, backend=None, environ=None):
        self._backend_override = backend
        self._environ = os.environ if environ is None else environ

    def __repr__(self):
        return "SecretStore(значения скрыты)"

    def _backend(self):
        if self._backend_override is not None:
            return self._backend_override
        import keyring  # импортируем при первом использовании
        return keyring

    def get(self, name: str) -> str | None:
        """Ключ из хранилища Windows, иначе из переменной окружения, иначе None."""
        try:
            value = self._backend().get_password(SERVICE, name)
        except Exception as e:  # хранилище недоступно — не падаем, просто ключа нет
            log.warning("хранилище секретов недоступно: %s", type(e).__name__)
            value = None
        if not value:
            value = self._environ.get(ENV_PREFIX + name.upper())
        return value or None

    def has(self, name: str) -> bool:
        return self.get(name) is not None

    def set(self, name: str, value: str) -> None:
        if not value.strip():
            raise ValueError("пустой ключ")
        self._backend().set_password(SERVICE, name, value.strip())

    def delete(self, name: str) -> None:
        self._backend().delete_password(SERVICE, name)


def main(argv: list[str]) -> int:
    if len(argv) != 2 or argv[0] not in ("set", "check", "delete"):
        print(__doc__)
        return 2
    action, name = argv
    store = SecretStore()
    if action == "set":
        value = getpass.getpass(f"Вставь значение «{name}» (ввод не отображается) и нажми Enter: ")
        store.set(name, value)
        print(f"Сохранено в Диспетчере учётных данных Windows как {SERVICE} / {name}.")
    elif action == "check":
        print(f"«{name}»: {'есть' if store.has(name) else 'нет'}.")
    else:
        store.delete(name)
        print(f"«{name}» удалён.")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
