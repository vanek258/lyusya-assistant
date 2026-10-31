"""AIRouter: выбор провайдера, резерв, ошибки, временное отключение, дневной лимит."""

import unittest
from datetime import date

from ai.provider import (USER, AuthError, DailyLimitReached, Message, ModelUnavailable, NetworkError,
                         NoProviderAvailable, ProviderTimeout, QuotaError)
from ai.providers.fake import FakeProvider
from ai.router import CHAT, CODING, COMPLEX, COOLDOWN_SECONDS, AIRouter
from dialogue import DialogueManager
from events import TYPED, Reply, Utterance


def config(fallback=False, limit=200):
    return {
        "cloud": {"enabled": True, "allow_fallback": fallback, "daily_request_limit": limit},
        "ai": {"providers": {"main": {"timeout": 7}},
               "routing": {"chat": ["main", "backup"], "coding": ["coder", "main"]}},
    }


def ask(router, text="привет"):
    return router.ask([Message(USER, text)], system="ты Люся")


class RouterTest(unittest.TestCase):
    def setUp(self):
        self.now = 0.0
        self.day = date(2026, 11, 1)

    def make(self, providers, **kwargs):
        return AIRouter(config(**kwargs), providers, clock=lambda: self.now, today=lambda: self.day)

    def test_answer_from_first_provider(self):
        main = FakeProvider("main", reply="Привет!")
        result = ask(self.make({"main": main}))
        self.assertEqual((result.text, result.provider), ("Привет!", "main"))
        messages, system, timeout = main.calls[0]
        self.assertEqual((messages[0].text, system, timeout), ("привет", "ты Люся", 7.0))

    def test_no_fallback_unless_allowed(self):
        main = FakeProvider("main", error=NetworkError())
        backup = FakeProvider("backup")
        with self.assertLogs("ai", level="WARNING"), self.assertRaises(NetworkError):
            ask(self.make({"main": main, "backup": backup}))
        self.assertEqual(backup.calls, [])

    def test_fallback_when_allowed(self):
        router = self.make({"main": FakeProvider("main", error=ProviderTimeout()),
                            "backup": FakeProvider("backup", reply="Запасной ответ.")}, fallback=True)
        with self.assertLogs("ai", level="WARNING"):
            self.assertEqual(ask(router).provider, "backup")

    def test_each_error_type_reaches_user_message(self):
        for error in (AuthError(), QuotaError(), NetworkError(), ProviderTimeout(), ModelUnavailable()):
            router = self.make({"main": FakeProvider("main", error=error)})
            with self.assertLogs("ai", level="WARNING"), self.assertRaises(type(error)) as ctx:
                ask(router)
            self.assertTrue(ctx.exception.user_message)

    def test_unavailable_provider_is_skipped(self):
        router = self.make({"main": FakeProvider("main", is_available=False)})
        with self.assertRaises(NoProviderAvailable):
            ask(router)

    def test_no_providers(self):
        with self.assertRaises(NoProviderAvailable):
            ask(self.make({}))

    def test_cooldown_after_repeated_failures(self):
        main = FakeProvider("main", error=NetworkError())
        router = self.make({"main": main})
        with self.assertLogs("ai", level="WARNING"):
            for _ in range(3):
                with self.assertRaises(NetworkError):
                    ask(router)
        with self.assertRaises(NoProviderAvailable):  # отключён — даже не вызывается
            ask(router)
        self.assertEqual(len(main.calls), 3)
        self.now += COOLDOWN_SECONDS + 1
        main.error = None
        self.assertEqual(ask(router).provider, "main")

    def test_daily_limit(self):
        router = self.make({"main": FakeProvider("main")}, limit=2)
        ask(router)
        ask(router)
        with self.assertRaises(DailyLimitReached):
            ask(router)
        self.day = date(2026, 11, 2)  # новый день — лимит обнулился
        self.assertEqual(ask(router).provider, "main")

    def test_task_routing(self):
        coder = FakeProvider("coder", reply="код")
        router = self.make({"main": FakeProvider("main"), "coder": coder})
        self.assertEqual(ask(router, "почини ошибку в функции на python").provider, "coder")

    def test_classify(self):
        self.assertEqual(AIRouter.classify("как дела"), CHAT)
        self.assertEqual(AIRouter.classify("объясни почему небо синее"), COMPLEX)
        self.assertEqual(AIRouter.classify("напиши скрипт на python"), CODING)

    def test_log_does_not_contain_conversation(self):
        router = self.make({"main": FakeProvider("main", error=NetworkError())})
        with self.assertLogs("ai", level="INFO") as logs, self.assertRaises(NetworkError):
            ask(router, "мой секретный вопрос")
        self.assertNotIn("секретный", "\n".join(logs.output))


class DialogueWithAITest(unittest.TestCase):
    def reply(self, dm, text) -> Reply:
        dm.submit(Utterance(text, source=TYPED))
        while True:
            item = dm.outbox.get(timeout=2)
            if isinstance(item, Reply):
                return item

    def make_dm(self, provider):
        cfg = {"assistant_name": "Люся", **config()}
        dm = DialogueManager(cfg, ai=AIRouter(cfg, {"main": provider}))
        if dm.ducker is not None:
            dm.ducker.shutdown()
            dm.ducker = None
        self.addCleanup(dm.shutdown)
        return dm

    def test_question_is_answered_by_ai(self):
        dm = self.make_dm(FakeProvider("main", reply="Небо синее из-за рассеяния света."))
        self.assertEqual(self.reply(dm, "почему небо синее").text, "Небо синее из-за рассеяния света.")

    def test_provider_error_becomes_friendly_reply(self):
        dm = self.make_dm(FakeProvider("main", error=NetworkError()))
        with self.assertLogs("ai", level="WARNING"):
            r = self.reply(dm, "почему небо синее")
        self.assertFalse(r.ok)
        self.assertIn("Нет связи", r.text)

    def test_local_command_never_reaches_ai(self):
        provider = FakeProvider("main")
        dm = self.make_dm(provider)
        r = self.reply(dm, "помощь")  # известная локальная команда без побочных действий
        self.assertIn("Скажи «Люся»", r.text)
        self.assertEqual(provider.calls, [])


if __name__ == "__main__":
    unittest.main()
