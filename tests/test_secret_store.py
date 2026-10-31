"""Хранилище ключей — с подменённым хранилищем, настоящий Диспетчер учётных данных не трогаем."""

import io
import unittest
from contextlib import redirect_stdout
from unittest import mock

import secret_store
from secret_store import SERVICE, SecretStore

SECRET = "AIza-тестовое-значение-1234567890"


class FakeKeyring:
    def __init__(self, fail=False):
        self.data = {}
        self.fail = fail

    def get_password(self, service, name):
        if self.fail:
            raise RuntimeError("хранилище недоступно")
        return self.data.get((service, name))

    def set_password(self, service, name, value):
        self.data[(service, name)] = value

    def delete_password(self, service, name):
        del self.data[(service, name)]


class SecretStoreTest(unittest.TestCase):
    def test_set_get_delete(self):
        backend = FakeKeyring()
        store = SecretStore(backend=backend, environ={})
        store.set("gemini_api_key", f"  {SECRET}\n")
        self.assertEqual(backend.data[(SERVICE, "gemini_api_key")], SECRET)  # пробелы обрезаны
        self.assertEqual(store.get("gemini_api_key"), SECRET)
        store.delete("gemini_api_key")
        self.assertIsNone(store.get("gemini_api_key"))

    def test_missing_key(self):
        store = SecretStore(backend=FakeKeyring(), environ={})
        self.assertIsNone(store.get("gemini_api_key"))
        self.assertFalse(store.has("gemini_api_key"))

    def test_env_fallback_for_tests(self):
        store = SecretStore(backend=FakeKeyring(), environ={"LYUSYA_GEMINI_API_KEY": SECRET})
        self.assertEqual(store.get("gemini_api_key"), SECRET)

    def test_keyring_value_wins_over_env(self):
        backend = FakeKeyring()
        backend.data[(SERVICE, "gemini_api_key")] = "из-хранилища"
        store = SecretStore(backend=backend, environ={"LYUSYA_GEMINI_API_KEY": "из-окружения"})
        self.assertEqual(store.get("gemini_api_key"), "из-хранилища")

    def test_broken_keyring_does_not_crash_or_leak(self):
        store = SecretStore(backend=FakeKeyring(fail=True), environ={})
        with self.assertLogs("secrets", level="WARNING") as logs:
            self.assertIsNone(store.get("gemini_api_key"))
        self.assertNotIn(SECRET, "\n".join(logs.output))

    def test_empty_value_is_refused(self):
        with self.assertRaises(ValueError):
            SecretStore(backend=FakeKeyring(), environ={}).set("gemini_api_key", "   ")

    def test_repr_hides_values(self):
        store = SecretStore(backend=FakeKeyring(), environ={"LYUSYA_GEMINI_API_KEY": SECRET})
        self.assertNotIn(SECRET, repr(store))

    def test_cli_never_prints_the_key(self):
        backend = FakeKeyring()
        with mock.patch.object(secret_store, "SecretStore", lambda: SecretStore(backend=backend, environ={})), \
                mock.patch.object(secret_store.getpass, "getpass", return_value=SECRET), \
                mock.patch.object(secret_store, "ask_in_window", return_value=SECRET):
            out = io.StringIO()
            with redirect_stdout(out):
                secret_store.main(["set", "gemini_api_key"])          # через окошко
                secret_store.main(["set-console", "gemini_api_key"])  # через терминал
                secret_store.main(["check", "gemini_api_key"])
        self.assertNotIn(SECRET, out.getvalue())
        self.assertIn("есть", out.getvalue())
        self.assertEqual(backend.data[(SERVICE, "gemini_api_key")], SECRET)

    def test_closed_window_saves_nothing(self):
        backend = FakeKeyring()
        with mock.patch.object(secret_store, "SecretStore", lambda: SecretStore(backend=backend, environ={})), \
                mock.patch.object(secret_store, "ask_in_window", return_value=None):
            with redirect_stdout(io.StringIO()):
                self.assertEqual(secret_store.main(["set", "gemini_api_key"]), 1)
        self.assertEqual(backend.data, {})


if __name__ == "__main__":
    unittest.main()
