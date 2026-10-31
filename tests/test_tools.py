"""Каталог действий: белые списки, риски, подтверждение."""

import tempfile
import unittest
from pathlib import Path

from commands import CLOSE, MEDIA, MUSIC, OPEN, VOLUME, Command
from dialogue import DialogueManager
from events import Reply, Utterance
from executor import Response
from tools import NEEDS_CONFIRMATION, Risk, ToolCall, ToolManager


class RecordingExecutor:
    site_aliases = {"ютуб": {"url": "https://www.youtube.com"}}
    program_aliases = {"браузер": {"key": "browser"}, "блокнот": {"key": "notepad"}}

    def __init__(self, found=None):
        self.found = found  # что вернёт поиск файла
        self.commands = []

    def execute(self, cmd):
        self.commands.append((cmd.intent, cmd.argument))
        return Response("Готово.")

    def _find_file(self, name):
        return self.found


class ToolManagerTest(unittest.TestCase):
    def setUp(self):
        self.executor = RecordingExecutor()
        self.tools = ToolManager(self.executor)

    def test_command_mapping(self):
        f = self.tools.from_command
        self.assertEqual(f(Command(OPEN, "ютуб")).name, "open_site")
        self.assertEqual(f(Command(OPEN, "браузер")).name, "open_app")
        self.assertEqual(f(Command(OPEN, "отчёт")).name, "open_file")
        self.assertEqual(f(Command(CLOSE, "браузер")).name, "close_app")
        self.assertEqual(f(Command(MUSIC)).name, "play_music")
        self.assertEqual(f(Command(MEDIA, "next")).args, {"action": "next"})
        self.assertEqual(f(Command(VOLUME, "up")).args, {"action": "up"})

    def test_allowed_program_runs(self):
        self.assertTrue(self.tools.call(ToolCall("open_app", {"name": "браузер"})).ok)
        self.assertEqual(self.executor.commands, [(OPEN, "браузер")])

    def test_program_outside_allowlist_is_refused(self):
        response = self.tools.call(ToolCall("open_app", {"name": "regedit"}))
        self.assertFalse(response.ok)
        self.assertEqual(self.executor.commands, [])

    def test_close_outside_allowlist_is_refused(self):
        self.assertFalse(self.tools.call(ToolCall("close_app", {"name": "explorer"})).ok)
        self.assertEqual(self.executor.commands, [])

    def test_site_outside_allowlist_is_refused(self):
        self.assertFalse(self.tools.call(ToolCall("open_site", {"name": "evil.example"})).ok)

    def test_unknown_tool_is_refused(self):
        self.assertFalse(self.tools.call(ToolCall("delete_everything")).ok)

    def test_media_and_volume_values_are_checked(self):
        self.assertFalse(self.tools.call(ToolCall("media", {"action": "format_c"})).ok)
        self.assertFalse(self.tools.call(ToolCall("volume", {"action": 100})).ok)
        self.assertEqual(self.executor.commands, [])

    def test_executable_needs_confirmation(self):
        self.executor.found = Path("C:/Downloads/setup.exe")
        response = self.tools.call(ToolCall("open_file", {"name": "setup"}))
        self.assertEqual(response.effect, NEEDS_CONFIRMATION)
        self.assertEqual(self.executor.commands, [])
        self.assertTrue(self.tools.call(ToolCall("open_file", {"name": "setup"}), confirmed=True).ok)
        self.assertEqual(self.executor.commands, [(OPEN, str(Path("C:/Downloads/setup.exe")))])

    def test_document_opens_without_confirmation(self):
        self.executor.found = Path("C:/Documents/отчёт.docx")
        self.assertTrue(self.tools.call(ToolCall("open_file", {"name": "отчёт"})).ok)

    def test_existing_path_is_used_directly(self):
        with tempfile.NamedTemporaryFile(suffix=".txt", delete=False) as f:
            path = Path(f.name)
        self.addCleanup(path.unlink)
        self.assertTrue(self.tools.call(ToolCall("open_file", {"name": str(path)})).ok)

    def test_missing_file(self):
        self.assertFalse(self.tools.call(ToolCall("open_file", {"name": "нет такого"})).ok)

    def test_risk_levels(self):
        self.assertIs(ToolManager.file_risk(Path("a.ps1")), Risk.HIGH)
        self.assertIs(ToolManager.file_risk(Path("a.LNK")), Risk.HIGH)
        self.assertIs(ToolManager.file_risk(Path("a.pdf")), Risk.LOW)


class ConfirmationFlowTest(unittest.TestCase):
    """Подтверждение через ядро диалога: «да», «нет», другая фраза, истёкший срок."""

    def setUp(self):
        self.now = 0.0
        self.executor = RecordingExecutor(found=Path("C:/Downloads/setup.exe"))
        self.dm = DialogueManager({"assistant_name": "Люся"}, executor=self.executor,
                                  clock=lambda: self.now)
        if self.dm.ducker is not None:  # музыку в тестах не трогаем
            self.dm.ducker.shutdown()
            self.dm.ducker = None
        self.addCleanup(self.dm.shutdown)

    def say(self, text) -> Reply:
        self.dm.submit(Utterance(text))
        while True:
            item = self.dm.outbox.get(timeout=2)
            if isinstance(item, Reply):
                return item

    def test_yes_runs_the_action(self):
        self.assertEqual(self.say("открой setup").effect, NEEDS_CONFIRMATION)
        self.assertTrue(self.say("да").ok)
        self.assertEqual(len(self.executor.commands), 1)

    def test_no_cancels(self):
        self.say("открой setup")
        self.assertIn("не буду", self.say("нет").text)
        self.assertEqual(self.executor.commands, [])

    def test_other_phrase_cancels_and_is_processed(self):
        self.say("открой setup")
        self.say("пауза")
        self.assertEqual(self.executor.commands, [(MEDIA, "pause")])
        reply = self.say("да")  # подтверждать уже нечего — это просто непонятная фраза
        self.assertEqual(self.executor.commands, [(MEDIA, "pause")])
        self.assertIn("не умею", reply.text)

    def test_expired_confirmation_is_ignored(self):
        self.say("открой setup")
        self.now = 11.0  # прошло больше 10 секунд
        self.say("да")
        self.assertNotIn((OPEN, str(Path("C:/Downloads/setup.exe"))), self.executor.commands)


if __name__ == "__main__":
    unittest.main()
