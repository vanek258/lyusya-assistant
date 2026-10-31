"""Ядро диалога без окна: фразы → ответы, события речи, пауза музыки."""

import queue
import threading
import unittest

from dialogue import DialogueManager
from events import HEARD, LISTENING, NOTICE, THINKING, TIMEOUT, TYPED, VOICE, Reply, StateEvent, Utterance
from executor import Response

CONFIG = {"assistant_name": "Люся", "programs": {}, "sites": {}}


class FakeExecutor:
    site_aliases = {"ютуб": {}}
    program_aliases = {"браузер": {}, "блокнот": {}}

    def __init__(self, response=None, error=None, gate=None):
        self.response = response or Response("Готово.", effect="launch")
        self.error = error
        self.gate = gate  # threading.Event: держит выполнение, пока тест не отпустит
        self.commands = []

    def _find_file(self, name):
        return None

    def execute(self, cmd):
        self.commands.append(cmd)
        if self.gate is not None:
            self.gate.wait(2)
        if self.error:
            raise self.error
        return self.response


class FakeDucker:
    def __init__(self):
        self.calls = []

    def duck(self):
        self.calls.append("duck")

    def unduck(self):
        self.calls.append("unduck")

    def forget(self):
        self.calls.append("forget")

    def shutdown(self):
        pass


class DialogueTest(unittest.TestCase):
    def make(self, **kwargs):
        self.executor = FakeExecutor(**kwargs)
        self.ducker = FakeDucker()
        dm = DialogueManager(CONFIG, executor=self.executor, ducker=self.ducker)
        self.addCleanup(dm.shutdown)
        return dm

    def next_reply(self, dm, timeout=2) -> Reply:
        while True:
            item = dm.outbox.get(timeout=timeout)
            if isinstance(item, Reply):
                return item

    def drain(self, dm):
        items = []
        while True:
            try:
                items.append(dm.outbox.get_nowait())
            except queue.Empty:
                return items

    def test_typed_command_goes_to_executor(self):
        dm = self.make()
        request_id = dm.submit(Utterance("открой браузер", source=TYPED))
        reply = self.next_reply(dm)
        self.assertEqual((reply.text, reply.ok, reply.effect, reply.request_id),
                         ("Готово.", True, "launch", request_id))
        self.assertEqual(self.executor.commands[0].argument, "браузер")

    def test_thinking_state_before_reply(self):
        dm = self.make()
        dm.submit(Utterance("пауза"))
        self.assertEqual(dm.outbox.get(timeout=2), StateEvent(THINKING))

    def test_empty_text_is_ignored(self):
        dm = self.make()
        self.assertIsNone(dm.submit(Utterance("   ")))

    def test_busy_drops_new_phrase(self):
        gate = threading.Event()
        dm = self.make(gate=gate)
        self.assertIsNotNone(dm.submit(Utterance("открой браузер")))
        self.assertTrue(dm.busy)
        self.assertIsNone(dm.submit(Utterance("закрой браузер")))
        gate.set()
        self.next_reply(dm)
        self.assertFalse(dm.busy)
        self.assertEqual(len(self.executor.commands), 1)

    def test_executor_crash_becomes_error_reply(self):
        dm = self.make(error=RuntimeError("всё сломалось"))
        with self.assertLogs("dialogue", level="ERROR"):
            dm.submit(Utterance("открой браузер"))
            reply = self.next_reply(dm)
        self.assertFalse(reply.ok)
        self.assertFalse(dm.busy)

    def test_cancelled_reply_is_dropped(self):
        gate = threading.Event()
        dm = self.make(gate=gate)
        dm.submit(Utterance("открой браузер"))
        dm.cancel_pending()
        gate.set()
        with self.assertRaises(queue.Empty):
            self.next_reply(dm, timeout=0.5)

    def test_voice_flow_ducks_and_unducks(self):
        dm = self.make()
        dm.voice_sink.put(("wake", ""))
        dm.voice_sink.put(("partial", "открой"))
        dm.voice_sink.put(("command", "открой браузер", 0.9))
        reply = self.next_reply(dm)
        self.assertTrue(reply.ok)
        states = [i for i in self.drain(dm) if isinstance(i, StateEvent)]
        self.assertNotIn(StateEvent(LISTENING), states)  # уже забраны next_reply
        self.assertEqual(self.ducker.calls, ["duck", "unduck"])

    def test_events_order_for_voice(self):
        dm = self.make()
        dm.voice_sink.put(("wake", ""))
        dm.voice_sink.put(("partial", "откр"))
        self.assertEqual(dm.outbox.get(timeout=1), StateEvent(LISTENING))
        self.assertEqual(dm.outbox.get(timeout=1), StateEvent(HEARD, "откр"))

    def test_music_command_keeps_music_decision(self):
        dm = self.make(response=Response("Пауза.", effect="music_off"))
        dm.voice_sink.put(("wake", ""))
        dm.voice_sink.put(("command", "пауза"))
        self.next_reply(dm)
        self.assertEqual(self.ducker.calls, ["duck", "forget"])

    def test_timeout_unducks(self):
        dm = self.make()
        dm.voice_sink.put(("wake", ""))
        dm.voice_sink.put(("timeout", ""))
        self.assertEqual(self.ducker.calls, ["duck", "unduck"])
        self.assertIn(StateEvent(TIMEOUT), self.drain(dm))

    def test_wake_while_busy_is_ignored(self):
        gate = threading.Event()
        dm = self.make(gate=gate)
        dm.submit(Utterance("открой браузер"))
        dm.voice_sink.put(("wake", ""))
        self.assertNotIn("duck", self.ducker.calls)
        gate.set()
        self.next_reply(dm)

    def test_listener_errors_become_notice(self):
        dm = self.make()
        dm.voice_sink.put(("error", "Микрофон недоступен"))
        self.assertEqual(dm.outbox.get(timeout=1), StateEvent(NOTICE, "Микрофон недоступен"))

    def test_voice_utterance_carries_confidence(self):
        dm = self.make()
        seen = []
        dm._handle = lambda utt: (seen.append(utt), Response("ок"))[1]
        dm.voice_sink.put(("command", "открой браузер", 0.42))
        self.next_reply(dm)
        self.assertEqual((seen[0].source, seen[0].confidence), (VOICE, 0.42))


class ClarifyTest(unittest.TestCase):
    """Переспрос сомнительных фраз (облако включено, но ИИ подменён)."""

    def setUp(self):
        config = {**CONFIG, "cloud": {"enabled": True, "max_words": 25, "min_confidence": 0.75}}
        self.dm = DialogueManager(config, executor=FakeExecutor(), ducker=FakeDucker())
        self.addCleanup(self.dm.shutdown)
        self.asked = []
        self.dm._ask_ai = lambda utt: (self.asked.append(utt.text), Response("Ответ ИИ."))[1]
        self.followups = []
        self.dm.on_followup = lambda: self.followups.append(True)

    def reply(self, utterance) -> Reply:
        self.dm.submit(utterance)
        while True:
            item = self.dm.outbox.get(timeout=2)
            if isinstance(item, Reply):
                return item

    def test_unsure_voice_is_asked_then_sent_after_yes(self):
        r = self.reply(Utterance("расскажи анекдот про котов", source=VOICE, confidence=0.4))
        self.assertIn("Ты сказал", r.text)
        self.assertEqual(self.asked, [])
        self.assertEqual(self.followups, [True])  # слушатель ждёт ответ без имени
        self.assertEqual(self.reply(Utterance("да", source=VOICE)).text, "Ответ ИИ.")
        self.assertEqual(self.asked, ["расскажи анекдот про котов"])

    def test_unsure_voice_with_no_is_not_sent(self):
        self.reply(Utterance("анекдот расскажи", source=VOICE))
        self.reply(Utterance("нет", source=VOICE))
        self.assertEqual(self.asked, [])

    def test_clear_question_goes_to_ai(self):
        r = self.reply(Utterance("расскажи анекдот про котов", source=VOICE, confidence=0.95))
        self.assertEqual(r.text, "Ответ ИИ.")

    def test_voice_without_wake_is_ignored_silently(self):
        r = self.reply(Utterance("расскажи анекдот про котов", source=VOICE, wake_confirmed=False))
        self.assertEqual(r.effect, "ignored")
        self.assertEqual(self.asked, [])


class CloudDisabledTest(unittest.TestCase):
    def test_unknown_phrase_answers_cannot(self):
        dm = DialogueManager(CONFIG, executor=FakeExecutor(), ducker=FakeDucker())
        self.addCleanup(dm.shutdown)
        dm.submit(Utterance("расскажи анекдот про котов"))
        while True:
            item = dm.outbox.get(timeout=2)
            if isinstance(item, Reply):
                break
        self.assertIn("пока не умею", item.text)


if __name__ == "__main__":
    unittest.main()
