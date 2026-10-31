"""Голосовой ввод через Vosk (офлайн, русский язык).

Слушает микрофон в отдельном потоке. Когда слышит имя («Люся»),
играет короткий сигнал и ждёт команду. Можно сказать всё сразу:
«Люся, открой браузер», а можно с паузой: «Люся» → дзинь → «открой браузер».

Имя ищется по началу слова: «люсь…» подходит и для «Люська», «Люсь»,
«люсе…» — для «Люсенька», но «люстра» и «Люда» не подходят.

Защита от случайных срабатываний: команда принимается только после имени
и только короткая — длинная фраза скорее подслушана из видео или песни.

Результаты отправляются в очередь событий:
  ("wake", "")        — услышала имя, сигнал уже прозвучал
  ("partial", текст)  — что слышно прямо сейчас (для облачка)
  ("command", текст)  — готовая команда
  ("timeout", "")     — после имени ничего не сказали
  ("error", текст)    — нет модели, библиотек или микрофона
"""

import ctypes
import json
import logging
import math
import os
import queue
import threading
import time
from array import array
from pathlib import Path

import sounds
from commands import UNKNOWN, normalize, parse

# Журнал голоса (logs/voice.log): что слышно, громкость микрофона, сбои потока.
# Нужен, чтобы разбираться, почему она не услышала команду.
log = logging.getLogger("voice")


def ascii_path(path: Path) -> str:
    """Vosk не умеет открывать пути с кириллицей (C:\\Users\\Пользователь\\...).

    Windows хранит для каждой папки короткое латинское имя (вида C:\\Users\\73B5~1),
    его и отдаём модели. Если коротких имён нет — пробуем относительный путь.
    """
    buf = ctypes.create_unicode_buffer(1024)
    if ctypes.windll.kernel32.GetShortPathNameW(str(path), buf, len(buf)) and buf.value.isascii():
        return buf.value
    relative = os.path.relpath(path)
    return relative if relative.isascii() else str(path)


def pick_microphone(sd) -> tuple[int, int, int]:
    """Выбирает микрофон через WASAPI на его родной частоте (обычно 48 кГц).

    Возвращает (номер устройства, частота, число каналов).
    """
    device = sd.default.device[0]
    for api in sd.query_hostapis():
        if "WASAPI" in api["name"] and api["default_input_device"] >= 0:
            device = api["default_input_device"]
            break
    info = sd.query_devices(device)
    return device, int(info["default_samplerate"]), max(1, min(2, info["max_input_channels"]))


def raw_settings(sd):
    """Настройки WASAPI для «сырого» микрофона — без системной обработки звука.

    Обычный микрофон Intel Smart Sound пропускает звук через подавление шума
    и эха. Эта обработка грузит звуковой движок Windows (~30% ядра вместо ~3%),
    из-за чего хрипела музыка, и вырезает всё, что звучит рядом с динамиками —
    поэтому при включённой музыке голос почти не доходил до распознавания.
    """
    settings = sd.WasapiSettings()
    settings._streaminfo.streamOption = sd._lib.eStreamOptionRaw  # в sounddevice нет параметра для этого
    return settings


class VoiceListener(threading.Thread):
    def __init__(self, config: dict, events: queue.Queue):
        super().__init__(daemon=True)
        self.events = events
        self.name = config.get("assistant_name", "Люся")
        self.model_path = Path(__file__).parent / config.get("voice_model", "models/vosk-model-small-ru-0.22")
        self.wake_words = {normalize(w) for w in config.get("wake_words", ["люся", "люсь"])}
        self.timeout = config.get("command_timeout", 7)
        self.max_command_words = config.get("max_command_words", 6)
        self.raw_mic = config.get("raw_microphone", True)
        self.audio: queue.Queue[bytes] = queue.Queue()
        self.channels = 1
        self._last_partial = ""
        self._level_sum = 0.0    # для средней громкости микрофона в журнале
        self._level_count = 0
        self._level_time = time.monotonic()

    def run(self):
        try:
            import sounddevice as sd
            import vosk
        except ImportError:
            self._emit("error", "Нет библиотек для голоса: pip install -r requirements.txt")
            return
        if not self.model_path.is_dir():
            self._emit("error", f"Не нашла модель речи в {self.model_path}")
            return

        vosk.SetLogLevel(-1)
        model = vosk.Model(ascii_path(self.model_path))
        try:
            device, rate, self.channels = pick_microphone(sd)
            recognizer = vosk.KaldiRecognizer(model, rate)
            stream = None
            if self.raw_mic:
                try:
                    stream = self._open_stream(sd, device, rate, raw_settings(sd))
                except Exception:
                    log.warning("сырой режим микрофона не поддерживается, беру обычный")
            raw = stream is not None
            if stream is None:
                stream = self._open_stream(sd, device, rate, None)
            log.info("микрофон: %s, %d Гц, каналов: %d, сырой режим: %s",
                     sd.query_devices(device)["name"], rate, self.channels, raw)
            with stream:
                self._loop(recognizer)
        except Exception as e:  # микрофон занят, отключён или запрещён в настройках
            log.exception("поток микрофона упал")
            self._emit("error", f"Микрофон недоступен: {e}")

    def _open_stream(self, sd, device, rate, settings):
        return sd.RawInputStream(device=device, samplerate=rate, blocksize=rate // 5, dtype="int16",
                                 channels=self.channels, latency="high", extra_settings=settings,
                                 callback=self._on_audio)

    def _on_audio(self, data, frames, time_info, status):
        if status:
            log.warning("сбой потока микрофона: %s", status)
        samples = array("h")
        samples.frombytes(bytes(data))
        if self.channels > 1:  # стерео → берём один канал
            samples = samples[::self.channels]
        self.audio.put(samples.tobytes())
        self._log_level(samples)

    def _log_level(self, samples):
        """Раз в 5 секунд пишет в журнал среднюю громкость микрофона и очередь звука."""
        if samples:
            self._level_sum += math.sqrt(sum(s * s for s in samples[::8]) / len(samples[::8]))
            self._level_count += 1
        if time.monotonic() - self._level_time >= 5:
            level = self._level_sum / max(self._level_count, 1)
            log.info("громкость микрофона %.0f, в очереди %d блоков", level, self.audio.qsize())
            self._level_sum, self._level_count, self._level_time = 0.0, 0, time.monotonic()

    def _emit(self, kind: str, text: str = ""):
        self.events.put((kind, text))

    def _split_wake(self, text: str) -> str | None:
        """Ищет имя в тексте. Возвращает слова после имени или None, если имени нет."""
        words = text.split()
        for i, word in enumerate(words):
            if word.startswith(tuple(self.wake_words)):
                return " ".join(words[i + 1:])
        return None

    def _is_command(self, text: str) -> bool:
        """Решает, похоже ли это на команду, которую говорят именно ей.

        Отсеивает одно непонятное слово (обычно само имя, услышанное неточно)
        и длинные фразы — это скорее подслушанный кусок видео или песни,
        выполнять такое нельзя.
        """
        words = text.split()
        if not words or len(words) > self.max_command_words:
            return False
        return not (len(words) == 1 and parse(text, self.name).intent == UNKNOWN)

    def _loop(self, recognizer):
        waiting = False  # имя прозвучало, ждём команду
        deadline = 0.0

        def start_waiting():
            nonlocal waiting, deadline
            if not waiting:
                log.info("услышала имя")
                sounds.play(sounds.WAKE)
                self._emit("wake")
            waiting = True
            deadline = time.monotonic() + self.timeout

        while True:
            try:
                data = self.audio.get(timeout=0.3)
            except queue.Empty:
                data = None

            if data is not None:
                if recognizer.AcceptWaveform(data):
                    # Фраза закончилась (пауза в речи) — итоговый текст
                    text = normalize(json.loads(recognizer.Result()).get("text", ""))
                    self._last_partial = ""
                    if text:
                        log.info("фраза: %s", text)
                    rest = self._split_wake(text)
                    if rest is not None:
                        start_waiting()
                    if waiting:
                        command = rest if rest is not None else text
                        if self._is_command(command):
                            log.info("команда: %s", command)
                            self._emit("command", command)
                            waiting = False
                else:
                    # Фраза ещё произносится — промежуточный текст
                    partial = normalize(json.loads(recognizer.PartialResult()).get("partial", ""))
                    if partial and partial != self._last_partial:
                        self._last_partial = partial
                        rest = self._split_wake(partial)
                        if rest is not None and not waiting:
                            start_waiting()  # сигнал сразу, не дожидаясь конца фразы
                            if not rest:
                                # После имени пока тишина: начинаем разбор заново, чтобы
                                # шум до имени (песня, видео) не склеился с командой
                                recognizer.Reset()
                                self._last_partial = ""
                                continue
                        if waiting:
                            self._emit("partial", rest if rest is not None else partial)
                            deadline = max(deadline, time.monotonic() + 3)  # пока говорят — ждём

            if waiting and time.monotonic() > deadline:
                waiting = False
                log.info("команду не дождалась")
                sounds.play(sounds.CANCEL)
                self._emit("timeout")
