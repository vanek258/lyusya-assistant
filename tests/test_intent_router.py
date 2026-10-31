"""Таблица решений IntentRouter из плана миграции (раздел 4.3) — целиком."""

import unittest

from events import TYPED, VOICE, Utterance
from intent_router import CLOUD_DISABLED, LONG_COMMAND, TOO_LONG, UNSURE, IntentRouter, Route

BASE = {"assistant_name": "Люся", "max_command_words": 6}
CLOUD_ON = {**BASE, "cloud": {"enabled": True, "max_words": 25, "min_confidence": 0.75}}


def voice(text, confidence=0.95, wake=True):
    return Utterance(text, source=VOICE, confidence=confidence, wake_confirmed=wake)


class RouterTest(unittest.TestCase):
    def decide(self, utterance, config=CLOUD_ON):
        return IntentRouter(config).decide(utterance)

    def test_known_command_is_local_even_with_cloud(self):
        d = self.decide(voice("открой браузер"))
        self.assertEqual((d.route, d.command.argument), (Route.LOCAL, "браузер"))

    def test_known_command_inside_long_phrase_is_clarified(self):
        d = self.decide(voice("а потом мы пошли гулять и закрой браузер наконец"))
        self.assertEqual((d.route, d.reason), (Route.CLARIFY, LONG_COMMAND))

    def test_long_typed_command_is_local(self):
        d = self.decide(Utterance("пожалуйста будь добра открой мне вот этот браузер", source=TYPED))
        self.assertIs(d.route, Route.LOCAL)

    def test_cloud_disabled(self):
        d = self.decide(voice("расскажи анекдот про программистов"), config=BASE)
        self.assertEqual((d.route, d.reason), (Route.CLARIFY, CLOUD_DISABLED))

    def test_cloud_disabled_by_default(self):
        d = self.decide(Utterance("какая погода в москве", source=TYPED), config={"assistant_name": "Люся"})
        self.assertEqual((d.route, d.reason), (Route.CLARIFY, CLOUD_DISABLED))

    def test_voice_without_wake_is_ignored(self):
        self.assertIs(self.decide(voice("расскажи анекдот про котов", wake=False)).route, Route.IGNORE)

    def test_short_phrase_is_clarified(self):
        d = self.decide(voice("анекдот расскажи"))
        self.assertEqual((d.route, d.reason), (Route.CLARIFY, UNSURE))

    def test_low_confidence_is_clarified(self):
        d = self.decide(voice("расскажи анекдот про программистов", confidence=0.5))
        self.assertEqual((d.route, d.reason), (Route.CLARIFY, UNSURE))

    def test_too_long_is_not_sent(self):
        d = self.decide(voice(" ".join(["слово"] * 26)))
        self.assertEqual((d.route, d.reason), (Route.CLARIFY, TOO_LONG))

    def test_typed_question_goes_to_cloud(self):
        self.assertIs(self.decide(Utterance("привет", source=TYPED)).route, Route.CLOUD)

    def test_clear_voice_question_goes_to_cloud(self):
        self.assertIs(self.decide(voice("расскажи анекдот про программистов")).route, Route.CLOUD)


if __name__ == "__main__":
    unittest.main()
