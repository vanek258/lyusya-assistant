"""Загрузка и проверка config.json."""

import json
import tempfile
import unittest
from pathlib import Path

from config import CLOUD_DEFAULTS, CONFIG_PATH, ConfigError, cloud_settings, load_config, validate


def minimal():
    return {
        "programs": {"browser": {"aliases": ["браузер"], "target": "chrome.exe", "process": "chrome.exe"}},
        "sites": {"youtube": {"aliases": ["ютуб"], "url": "https://www.youtube.com"}},
    }


class ConfigTest(unittest.TestCase):
    def write(self, text):
        f = tempfile.NamedTemporaryFile("w", suffix=".json", delete=False, encoding="utf-8")
        f.write(text)
        f.close()
        self.addCleanup(Path(f.name).unlink)
        return Path(f.name)

    def test_project_config_is_valid(self):
        load_config(CONFIG_PATH)

    def test_minimal_config_is_valid(self):
        self.assertEqual(validate(minimal()), [])

    def test_broken_json_reports_line(self):
        path = self.write('{\n  "programs": {,\n}')
        with self.assertRaises(ConfigError) as ctx:
            load_config(path)
        self.assertIn("строка 2", str(ctx.exception))

    def test_missing_file(self):
        with self.assertRaises(ConfigError):
            load_config(Path("нет-такого-файла.json"))

    def test_program_without_target(self):
        cfg = minimal()
        del cfg["programs"]["browser"]["target"]
        self.assertTrue(any("target" in e for e in validate(cfg)))

    def test_wrong_types(self):
        cfg = minimal()
        cfg.update(command_timeout="семь", raw_microphone=1, wake_words=[])
        errors = validate(cfg)
        self.assertTrue(any("command_timeout" in e for e in errors))
        self.assertTrue(any("raw_microphone" in e for e in errors))
        self.assertTrue(any("wake_words" in e for e in errors))

    def test_unknown_music_program(self):
        cfg = minimal()
        cfg["music_program"] = "spotify"
        self.assertTrue(any("music_program" in e for e in validate(cfg)))

    def test_file_with_bom_loads(self):
        path = self.write("﻿" + json.dumps(minimal()))  # так сохраняют Блокнот и PowerShell
        self.assertIn("programs", load_config(path))

    def test_stage1_config_without_new_sections_loads(self):
        cfg = minimal()  # как конфиг этапа 1: ни cloud, ни ai
        self.assertEqual(validate(cfg), [])
        self.assertEqual(cloud_settings(cfg), CLOUD_DEFAULTS)
        self.assertFalse(cloud_settings(cfg)["enabled"])

    def test_cloud_partial_settings_get_defaults(self):
        settings = cloud_settings({**minimal(), "cloud": {"enabled": True}})
        self.assertTrue(settings["enabled"])
        self.assertEqual(settings["daily_request_limit"], 200)

    def test_valid_cloud_and_ai(self):
        cfg = minimal()
        cfg["cloud"] = {"enabled": True, "allow_fallback": False, "max_words": 25,
                        "min_confidence": 0.75, "daily_request_limit": 200}
        cfg["ai"] = {"providers": {"gemini": {"model": "some-model", "timeout": 20}},
                     "routing": {"chat": ["gemini"], "complex": ["gemini"], "coding": ["gemini"]}}
        self.assertEqual(validate(cfg), [])

    def test_cloud_errors(self):
        cfg = minimal()
        cfg["cloud"] = {"enabled": "да", "min_confidence": 2, "max_words": 0, "enabeld": True}
        errors = "\n".join(validate(cfg))
        for word in ("enabled", "min_confidence", "max_words", "неизвестный параметр «enabeld»"):
            self.assertIn(word, errors)

    def test_ai_errors(self):
        cfg = minimal()
        cfg["ai"] = {"providers": {"gemini": {"timeout": -1}}, "routing": {"poetry": ["gemini"], "chat": "gemini"}}
        errors = "\n".join(validate(cfg))
        self.assertIn("timeout", errors)
        self.assertIn("неизвестный тип задачи «poetry»", errors)
        self.assertIn("routing → chat", errors)

    def test_secrets_are_refused_anywhere(self):
        cfg = minimal()
        cfg["ai"] = {"providers": {"gemini": {"api_key": "AIza..."}}}
        cfg["Token"] = "x"
        errors = "\n".join(validate(cfg))
        self.assertIn("ai → providers → gemini → api_key", errors)
        self.assertIn("Token", errors)
        self.assertIn("secret_store", errors)

    def test_program_named_like_secret_is_allowed(self):
        cfg = minimal()
        cfg["programs"]["keepass"] = {"aliases": ["кипасс"], "target": "KeePass.exe"}
        self.assertEqual(validate(cfg), [])
        cfg["programs"]["keepass"]["password"] = "123"  # а вот параметр внутри — нельзя
        self.assertTrue(any("programs → keepass → password" in e for e in validate(cfg)))

    def test_load_returns_dict(self):
        path = self.write(json.dumps(minimal()))
        self.assertIn("programs", load_config(path))


if __name__ == "__main__":
    unittest.main()
