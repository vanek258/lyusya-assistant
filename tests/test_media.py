"""Таймауты медиасессий и последовательная пауза музыки (Ducker)."""

import asyncio
import threading
import time
import unittest

import media


class RunTest(unittest.TestCase):
    def test_result(self):
        async def ok():
            return 42
        self.assertEqual(media._run(ok), 42)

    def test_error_is_raised(self):
        async def fail():
            raise OSError("плеер исчез")
        with self.assertRaises(OSError):
            media._run(fail)

    def test_timeout_is_explicit(self):
        async def slow():
            await asyncio.sleep(1)
        with self.assertRaises(media.MediaTimeout):
            media._run(slow, timeout=0.1)


class DuckerTest(unittest.TestCase):
    def setUp(self):
        self.calls = []

        def pause():
            time.sleep(0.2)  # пауза медленная — «продолжить» приходит, пока она идёт
            self.calls.append("pause")
            return ["Yandex.Music"]

        def resume(ids):
            self.calls.append(("resume", ids))

        self.ducker = media.Ducker(pause=pause, resume_fn=resume)
        self.addCleanup(self.ducker.shutdown)

    def test_unduck_waits_for_duck(self):
        self.ducker.duck()
        self.ducker.unduck().result(2)
        self.assertEqual(self.calls, ["pause", ("resume", ["Yandex.Music"])])

    def test_forget_prevents_resume(self):
        self.ducker.duck()
        self.ducker.forget()
        self.ducker.unduck().result(2)
        self.assertEqual(self.calls, ["pause"])

    def test_double_duck_pauses_once(self):
        self.ducker.duck()
        self.ducker.duck().result(2)
        self.assertEqual(self.calls, ["pause"])

    def test_errors_do_not_kill_worker(self):
        def broken():
            raise media.MediaTimeout("нет ответа")
        ducker = media.Ducker(pause=broken, resume_fn=lambda ids: None)
        self.addCleanup(ducker.shutdown)
        with self.assertLogs("media", level="ERROR"):
            ducker.duck().result(2)
        self.assertTrue(ducker.unduck().result(2) is None)  # поток жив и принимает задачи


if __name__ == "__main__":
    unittest.main()
