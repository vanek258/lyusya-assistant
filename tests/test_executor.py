"""Выполнение команд — системные действия подменены, ничего реально не запускается."""

import unittest
from unittest import mock

import executor
from commands import Command, CLOSE, MEDIA, MUSIC
from config import load_config


class CloseTest(unittest.TestCase):
    def setUp(self):
        self.ex = executor.Executor(load_config())
        patcher = mock.patch.object(executor, "system")
        self.system = patcher.start()
        self.addCleanup(patcher.stop)
        self.system.is_running.return_value = True

    def test_closes_only_main_windows(self):
        self.system.main_windows.return_value = [101, 102]
        response = self.ex.execute(Command(CLOSE, "браузер"))
        self.assertTrue(response.ok)
        self.system.close_windows.assert_called_once_with([101, 102])
        self.system.kill_process.assert_not_called()

    def test_background_process_without_windows_is_left_alone(self):
        self.system.main_windows.return_value = []
        response = self.ex.execute(Command(CLOSE, "браузер"))
        self.assertFalse(response.ok)
        self.system.close_windows.assert_not_called()
        self.system.kill_process.assert_not_called()

    def test_force_close_only_when_configured(self):
        self.ex.execute(Command(CLOSE, "дискорд"))  # в config.json у Discord force_close: true
        self.system.kill_process.assert_called_once_with("Discord.exe")

    def test_not_running(self):
        self.system.is_running.return_value = False
        response = self.ex.execute(Command(CLOSE, "браузер"))
        self.assertIn("и так закрыт", response.text)
        self.system.close_windows.assert_not_called()

    def test_unknown_program(self):
        response = self.ex.execute(Command(CLOSE, "фотошоп"))
        self.assertFalse(response.ok)


class MediaErrorsTest(unittest.TestCase):
    def setUp(self):
        self.ex = executor.Executor(load_config())

    def test_timeout_is_reported_honestly(self):
        with mock.patch.object(executor.media, "AVAILABLE", True), \
                mock.patch.object(executor.media, "skip", side_effect=executor.media.MediaTimeout()):
            response = self.ex.execute(Command(MEDIA, "next"))
        self.assertFalse(response.ok)
        self.assertIn("не знаю, сработало ли", response.text)

    def test_player_error_is_reported(self):
        with mock.patch.object(executor.media, "AVAILABLE", True), \
                mock.patch.object(executor.media, "play", side_effect=OSError("сбой WinRT")):
            response = self.ex.execute(Command(MUSIC))
        self.assertFalse(response.ok)


if __name__ == "__main__":
    unittest.main()
