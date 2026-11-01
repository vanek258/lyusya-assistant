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
  ("wake", "followup") — слушает ответ на свой вопрос (без имени)
  ("partial", текст)  — что слышно прямо сейчас (для облачка)
  ("command", текст, уверенность) — готовая команда и средняя уверенность
                       распознавания её слов (0…1)
  ("timeout", "")     — после имени ничего не сказали
  ("error", текст)    — нет модели, библиотек или микрофона
  ("notice", текст)   — служебное сообщение (например, включён подробный журнал)

Приватность: по умолчанию в журнал пишутся только технические события
(микрофон, громкость, сбои, «услышала имя»). Сами фразы пишутся, только если
в config.json включён debug_speech_log — и об этом сообщается при запуске.
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
from config import cloud_settings

# Журнал голоса (logs/voice.log): громкость микрофона, сбои потока, срабатывания имени.
# Нужен, чтобы разбираться, почему она не услышала команду.
log = logging.getLogger("voice")

# Сколько блоков звука (по 0,2 с) может ждать распознавания. Если распознавание
# не успевает, самые старые блоки выбрасываются — иначе задержка росла бы бесконечно.
AUDIO_QUEUE_BLOCKS = 25

FOLLOWUP = "followup"  # текст события wake: ждём ответ на вопрос Люси, а не новую команду

# Распознаватель Vosk хранит весь услышанный звук с момента создания (~7,5 МБ в минуту),
# поэтому раз в минуту заменяем его новым — только между фразами и не во время ожидания команды
RECOGNIZER_REFRESH_SECONDS = 60


def ascii_path(path: Path) -> str:
    """Vosk не умеет открывать пути с кириллицей (например, C:\\Users\\Иван\\...).

    Windows хранит для каждой папки короткое латинское имя (вида C:\\Users\\ABCD~1),
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
        # Длинные фразы — скорее подслушанный кусок видео или песни. Если включено облако,
        # пропускаем фразы подлиннее (вопросы к ИИ), их дальше проверит IntentRouter
        cloud = cloud_settings(config)
        self.max_command_words = max(config.get("max_command_words", 6),
                                     cloud["max_words"] if cloud["enabled"] else 0)
        self._followup = threading.Event()  # выслушать ответ «да / нет» без обращения по имени
        self.raw_mic = config.get("raw_microphone", True)
        self.debug_speech = config.get("debug_speech_log", False)
        self.audio: queue.Queue[bytes] = queue.Queue(maxsize=AUDIO_QUEUE_BLOCKS)
        self.dropped_blocks = 0  # сколько блоков выброшено из-за переполнения очереди
        self.refresh_seconds = RECOGNIZER_REFRESH_SECONDS
        self.recognizer_refreshes = 0
        self._stop_event = threading.Event()
        self.channels = 1
        self._last_partial = ""
        self._level_sum = 0.0    # для средней громкости микрофона в журнале
        self._level_count = 0
        self._level_time = time.monotonic()

    def listen_again(self):
        """Выслушать следующую фразу без имени — после вопроса Люси «Скажи «да»»."""
        self._followup.set()

    def stop(self, timeout: float = 2.0) -> bool:
        """Просит поток остановиться и ждёт его. True — поток завершился вовремя.

        Цикл проверяет флаг остановки не реже раза в 0,3 с, после выхода из него
        закрывается аудиопоток (with stream) и освобождается микрофон.
        """
        self._stop_event.set()
        if self.is_alive():
            self.join(timeout)
        if self.is_alive():
            log.warning("поток распознавания не остановился за %.1f с", timeout)
        return not self.is_alive()

    def run(self):
        if self.debug_speech:
            log.warning("включён подробный журнал речи: распознанные фразы пишутся в logs/voice.log")
            self._emit("notice", "Включён подробный журнал речи: всё, что я слышу, пишется в logs/voice.log.")
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
        try:
            model = vosk.Model(ascii_path(self.model_path))
        except Exception:  # модель повреждена или неполная
            log.exception("не удалось загрузить модель речи")
            self._emit("error", "Не получилось загрузить модель речи. Скачай её заново (см. README). "
                                "Голос пока не работает, команды можно писать текстом.")
            return
        try:
            device, rate, self.channels = pick_microphone(sd)

            def make_recognizer():
                recognizer = vosk.KaldiRecognizer(model, rate)
                recognizer.SetWords(True)  # уверенность для каждого слова
                return recognizer

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
                self._loop(make_recognizer(), make_recognizer)
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
        self._enqueue(samples.tobytes())
        self._log_level(samples)

    def _enqueue(self, block: bytes):
        """Кладёт блок в очередь; если она полна — выбрасывает самый старый блок.

        Для голосового помощника свежий звук важнее старого: лучше потерять
        полсекунды давней тишины, чем отвечать с накопившейся задержкой.
        """
        try:
            self.audio.put_nowait(block)
        except queue.Full:
            try:
                self.audio.get_nowait()
            except queue.Empty:
                pass
            self.dropped_blocks += 1
            try:
                self.audio.put_nowait(block)
            except queue.Full:
                self.dropped_blocks += 1

    def _log_level(self, samples):
        """Раз в 5 секунд пишет в журнал среднюю громкость микрофона и очередь звука."""
        if samples:
            self._level_sum += math.sqrt(sum(s * s for s in samples[::8]) / len(samples[::8]))
            self._level_count += 1
        if time.monotonic() - self._level_time >= 5:
            level = self._level_sum / max(self._level_count, 1)
            log.info("громкость микрофона %.0f, в очереди %d блоков, выброшено всего %d",
                     level, self.audio.qsize(), self.dropped_blocks)
            self._level_sum, self._level_count, self._level_time = 0.0, 0, time.monotonic()

    def _emit(self, kind: str, text: str = "", *extra):
        self.events.put((kind, text, *extra))

    def _confidence(self, result: dict) -> float:
        """Средняя уверенность слов команды (слов после имени, если оно есть в фразе).

        Если распознаватель не вернул сведений о словах — 1.0.
        """
        words = result.get("result") or []
        if not words:
            return 1.0
        prefixes = tuple(self.wake_words)
        name_at = next((i for i, w in enumerate(words) if normalize(w.get("word", "")).startswith(prefixes)), None)
        tail = words[name_at + 1:] if name_at is not None and name_at + 1 < len(words) else words
        return sum(w.get("conf", 1.0) for w in tail) / len(tail)

    def _split_wake(self, text: str) -> str | None:
        """Ищет имя в тексте. Возвращает слова после имени или None, если имени нет."""
        words = text.split()
        for i, word in enumerate(words):
            if word.startswith(tuple(self.wake_words)):
                return " ".join(words[i + 1:])
        return None

    def _is_command(self, text: str, answer: bool = False) -> bool:
        """Решает, похоже ли это на команду, которую говорят именно ей.

        Отсеивает одно непонятное слово (обычно само имя, услышанное неточно)
        и длинные фразы — это скорее подслушанный кусок видео или песни,
        выполнять такое нельзя. answer — ждём ответ на вопрос Люси: тогда
        одно слово («да», «нет») — нормальный ответ.
        """
        words = text.split()
        if not words or len(words) > self.max_command_words:
            return False
        if answer:
            return True
        return not (len(words) == 1 and parse(text, self.name).intent == UNKNOWN)

    def _loop(self, recognizer, make_recognizer=None):
        waiting = False  # имя прозвучало (или Люся задала вопрос), ждём фразу
        answer = False   # ждём именно ответ на вопрос Люси
        deadline = 0.0
        created = time.monotonic()

        def start_waiting(reason: str = ""):
            nonlocal waiting, answer, deadline
            if not waiting:
                log.info("жду ответ" if reason else "услышала имя")
                sounds.play(sounds.WAKE)
                self._emit("wake", reason)
                answer = reason == FOLLOWUP
            waiting = True
            deadline = time.monotonic() + self.timeout

        while not self._stop_event.is_set():
            if self._followup.is_set():  # Люся задала вопрос — ждём ответ без имени
                self._followup.clear()
                start_waiting(FOLLOWUP)
            try:
                data = self.audio.get(timeout=0.3)
            except queue.Empty:
                data = None

            if data is not None:
                if recognizer.AcceptWaveform(data):
                    # Фраза закончилась (пауза в речи) — итоговый текст
                    result = json.loads(recognizer.Result())
                    text = normalize(result.get("text", ""))
                    self._last_partial = ""
                    if text and self.debug_speech:
                        log.info("фраза: %s", text)
                    rest = self._split_wake(text)
                    if rest is not None:
                        start_waiting()
                    if waiting:
                        command = rest if rest is not None else text
                        if self._is_command(command, answer and rest is None):
                            if self.debug_speech:
                                log.info("команда: %s", command)
                            else:
                                log.info("команда принята (%d слов)", len(command.split()))
                            self._emit("command", command, self._confidence(result))
                            waiting = False
                    # Между фразами и не во время ожидания — время освободить накопленную память
                    if (make_recognizer is not None and not waiting
                            and time.monotonic() - created >= self.refresh_seconds):
                        recognizer = make_recognizer()
                        created = time.monotonic()
                        self.recognizer_refreshes += 1
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
