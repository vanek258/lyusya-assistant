"""Разбор фраз в команды."""

import unittest

from commands import CLOSE, EXIT, HELP, MEDIA, MUSIC, OPEN, UNKNOWN, VOLUME, parse


class ParseTest(unittest.TestCase):
    def check(self, text, intent, argument=""):
        cmd = parse(text)
        self.assertEqual((cmd.intent, cmd.argument), (intent, argument), text)

    def test_open_and_close(self):
        self.check("открой браузер", OPEN, "браузер")
        self.check("Люся, открой YouTube", OPEN, "youtube")
        self.check("закрой дискорд", CLOSE, "дискорд")

    def test_misheard_word_before_verb(self):
        # распознавание иногда слышит имя как другое слово
        self.check("клаву открой браузер", OPEN, "браузер")

    def test_music_and_media(self):
        self.check("включи музыку", MUSIC)
        self.check("включи музыку пожалуйста", MUSIC)
        self.check("пауза", MEDIA, "pause")
        self.check("выключи музыку", MEDIA, "pause")
        self.check("сними с паузы", MEDIA, "play")
        self.check("следующий трек", MEDIA, "next")
        self.check("предыдущий", MEDIA, "prev")

    def test_volume(self):
        self.check("сделай погромче", VOLUME, "up")
        self.check("тише", VOLUME, "down")
        self.check("выключи звук", VOLUME, "mute")

    def test_service(self):
        self.check("выключи ассистента", EXIT)
        self.check("помощь", HELP)
        self.check("", UNKNOWN)
        self.check("привет", UNKNOWN, "привет")


if __name__ == "__main__":
    unittest.main()
