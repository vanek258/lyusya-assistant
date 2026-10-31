"""Ядро диалога без окна: фразы → ответы, события речи, пауза музыки."""

import queue
import threading
import unittest

from dialogue import DialogueManager
from events import HEARD, LISTENING, NOTICE, THINKING, TIMEOUT, TYPED, VOICE, Reply, StateEvent, Utterance
from executor import Response

CONFIG = {"assistant_name": "Люся", "programs": {}, "sites": {}}


class FakeExecutor:
    def __init__(self, response=None, error=None, gate=None):
        self.response = response or Response("Готово.", effect="launch")
        self.error = error
        self.gate = gate  # threading.Event: держит выполнение, пока тест не отпустит
        self.commands = []

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


if __name__ == "__main__":
    unittest.main()
