"""Краткосрочная память и передача контекста и личности модели."""

import unittest

import persona
from ai.provider import ASSISTANT, USER, NetworkError
from ai.providers.fake import FakeProvider
from ai.router import AIRouter
from dialogue import DialogueManager
from events import TYPED, Reply, Utterance
from memory import MemoryManager


class MemoryTest(unittest.TestCase):
    def setUp(self):
        self.now = 0.0
        self.memory = MemoryManager(max_messages=4, idle_seconds=300, clock=lambda: self.now)

    def test_keeps_order(self):
        self.memory.add(USER, "найди ноутбук")
        self.memory.add(ASSISTANT, "для каких задач?")
        self.assertEqual([m.text for m in self.memory.context()], ["найди ноутбук", "для каких задач?"])

    def test_keeps_only_last_messages(self):
        for i in range(6):
            self.memory.add(USER, str(i))
        self.assertEqual([m.text for m in self.memory.context()], ["2", "3", "4", "5"])

    def test_forgets_after_silence(self):
        self.memory.add(USER, "старый вопрос")
        self.now = 301
        self.assertEqual(self.memory.context(), [])

    def test_clear(self):
        self.memory.add(USER, "вопрос")
        self.memory.clear()
        self.assertEqual(self.memory.context(), [])


class ContextTest(unittest.TestCase):
    def setUp(self):
        cfg = {"assistant_name": "Люся", "cloud": {"enabled": True}, "ai": {"routing": {"chat": ["main"]}}}
        self.provider = FakeProvider("main", reply="Для каких задач?")
        self.dm = DialogueManager(cfg, ai=AIRouter(cfg, {"main": self.provider}))
        if self.dm.ducker is not None:
            self.dm.ducker.shutdown()
            self.dm.ducker = None
        self.addCleanup(self.dm.shutdown)

    def reply(self, text) -> Reply:
        self.dm.submit(Utterance(text, source=TYPED))
        while True:
            item = self.dm.outbox.get(timeout=2)
            if isinstance(item, Reply):
                return item

    def test_second_question_gets_context_and_persona(self):
        self.reply("найди мне хороший ноутбук")
        self.provider.reply = "Смотри модели с 16 ГБ памяти."
        self.reply("для программирования")
        messages, system, _ = self.provider.calls[1]
        self.assertEqual([(m.role, m.text) for m in messages], [
            (USER, "найди мне хороший ноутбук"),
            (ASSISTANT, "Для каких задач?"),
            (USER, "для программирования"),
        ])
        self.assertEqual(system, persona.system_prompt("Люся"))

    def test_failed_exchange_is_not_remembered(self):
        self.provider.error = NetworkError()
        with self.assertLogs("ai", level="WARNING"):
            self.reply("вопрос, на который не ответили")
        self.assertEqual(self.dm.memory.context(), [])

    def test_local_commands_do_not_enter_conversation(self):
        self.reply("помощь")
        self.assertEqual(self.dm.memory.context(), [])

    def test_persona_forbids_claiming_actions(self):
        self.assertIn("никогда не пиши, что выполнила действие", persona.system_prompt())


if __name__ == "__main__":
    unittest.main()
