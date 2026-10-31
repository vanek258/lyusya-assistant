"""Загрузка и проверка config.json."""

import json
import tempfile
import unittest
from pathlib import Path

from config import CONFIG_PATH, ConfigError, load_config, validate


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

    def test_load_returns_dict(self):
        path = self.write(json.dumps(minimal()))
        self.assertIn("programs", load_config(path))


if __name__ == "__main__":
    unittest.main()
