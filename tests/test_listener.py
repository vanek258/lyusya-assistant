"""Логика голосового ввода — без микрофона и без Vosk (распознаватель подменён)."""

import json
import queue
import threading
import time
import unittest
from unittest import mock

import listener
from listener import AUDIO_QUEUE_BLOCKS, VoiceListener

CONFIG = {"wake_words": ["люся", "люсь"], "command_timeout": 1, "max_command_words": 6}


class FakeRecognizer:
    """Вместо Vosk: на каждый блок звука отдаёт заранее заданный результат.

    script — список ("partial", текст) или ("final", текст), по одному на блок.
    """

    def __init__(self, script):
        self.script = list(script)
        self.current = ("partial", "")

    def AcceptWaveform(self, data):
        self.current = self.script.pop(0) if self.script else ("partial", "")
        return self.current[0] == "final"

    def Result(self):
        return json.dumps({"text": self.current[1]})

    def PartialResult(self):
        return json.dumps({"partial": self.current[1]})

    def Reset(self):
        pass


class ListenerTest(unittest.TestCase):
    def setUp(self):
        patcher = mock.patch.object(listener.sounds, "play")
        patcher.start()
        self.addCleanup(patcher.stop)
        self.events = queue.Queue()
        self.listener = VoiceListener(dict(CONFIG), self.events)

    def run_script(self, script, extra_wait=0.3, config=None):
        """Прогоняет сценарий через _loop и возвращает события (без partial)."""
        if config:
            self.listener = VoiceListener({**CONFIG, **config}, self.events)
        lst = self.listener
        thread = threading.Thread(target=lst._loop, args=(FakeRecognizer(script),), daemon=True)
        thread.start()
        for _ in script:
            lst.audio.put(b"\0\0")
        time.sleep(extra_wait)
        lst._stop_event.set()
        thread.join(2)
        self.assertFalse(thread.is_alive(), "цикл не остановился по флагу")
        events = []
        while not self.events.empty():
            item = self.events.get()
            if item[0] != "partial":
                events.append(item)
        return events

    def test_name_then_command(self):
        events = self.run_script([("partial", "люся"), ("final", ""), ("final", "открой браузер")])
        self.assertEqual(events, [("wake", ""), ("command", "открой браузер", 1.0)])

    def test_name_and_command_in_one_phrase(self):
        events = self.run_script([("final", "люська сделай погромче")])
        self.assertEqual(events, [("wake", ""), ("command", "сделай погромче", 1.0)])

    def test_speech_without_name_is_ignored(self):
        events = self.run_script([("final", "закрой окно пожалуйста"), ("final", "люстра горит")])
        self.assertEqual(events, [])

    def test_long_phrase_after_name_is_not_executed(self):
        events = self.run_script([("final", "люся а потом мы пошли гулять и закрой браузер наконец")])
        self.assertEqual(events, [("wake", "")])

    def test_timeout_after_name(self):
        events = self.run_script([("final", "люся")], extra_wait=1.5)
        self.assertEqual(events, [("wake", ""), ("timeout", "")])

    def test_speech_is_not_logged_by_default(self):
        with self.assertLogs("voice", level="INFO") as logs:
            self.run_script([("final", "секретный разговор"), ("final", "люся открой браузер")])
        joined = "\n".join(logs.output)
        self.assertNotIn("секретный разговор", joined)
        self.assertNotIn("открой браузер", joined)

    def test_speech_is_logged_in_debug_mode(self):
        with self.assertLogs("voice", level="INFO") as logs:
            self.run_script([("final", "люся открой браузер")], config={"debug_speech_log": True})
        self.assertIn("открой браузер", "\n".join(logs.output))

    def test_confidence_of_words_after_name(self):
        result = {"result": [{"word": "люся", "conf": 1.0}, {"word": "открой", "conf": 0.8},
                             {"word": "браузер", "conf": 0.6}]}
        self.assertAlmostEqual(self.listener._confidence(result), 0.7)

    def test_confidence_without_word_info(self):
        self.assertEqual(self.listener._confidence({"text": "пауза"}), 1.0)

    def test_listen_again_waits_without_name(self):
        self.listener.listen_again()
        events = self.run_script([("final", "да")])
        self.assertEqual(events, [("wake", "followup"), ("command", "да", 1.0)])

    def test_cloud_allows_longer_phrases(self):
        phrase = "люся расскажи пожалуйста как устроены черные дыры во вселенной"
        self.assertEqual(self.run_script([("final", phrase)]), [("wake", "")])  # облако выключено
        self.events = queue.Queue()
        events = self.run_script([("final", phrase)], config={"cloud": {"enabled": True, "max_words": 25}})
        self.assertEqual(events[-1][:2], ("command", "расскажи пожалуйста как устроены черные дыры во вселенной"))

    def test_queue_is_bounded_and_drops_oldest(self):
        lst = self.listener
        for i in range(AUDIO_QUEUE_BLOCKS + 10):
            lst._enqueue(bytes([i]))
        self.assertEqual(lst.audio.qsize(), AUDIO_QUEUE_BLOCKS)
        self.assertEqual(lst.dropped_blocks, 10)
        self.assertEqual(lst.audio.get_nowait(), bytes([10]))  # самые старые выброшены

    def test_stop_without_start(self):
        self.assertTrue(self.listener.stop(timeout=0.1))

    def test_broken_model_reports_error(self):
        lst = VoiceListener({**CONFIG, "voice_model": "."}, self.events)  # папка есть, модели нет
        fake_vosk = mock.MagicMock()
        fake_vosk.Model.side_effect = Exception("Failed to create a model")
        with mock.patch.dict("sys.modules", {"vosk": fake_vosk, "sounddevice": mock.MagicMock()}), \
                self.assertLogs("voice", level="ERROR"):
            lst.run()
        kind, text = self.events.get_nowait()[:2]
        self.assertEqual(kind, "error")
        self.assertIn("модель речи", text)


if __name__ == "__main__":
    unittest.main()
