"""Ядро диалога: принимает фразы, решает, что с ними делать, и формирует ответы.

DialogueManager не знает про окно и Tkinter. Он получает фразы (с голоса через
VoiceSink или напечатанные через submit), выполняет их по одной в своём
фоновом потоке и кладёт ответы и состояния в очередь outbox, которую
забирает интерфейс.

Сюда же перенесено решение, когда ставить музыку на паузу: услышала имя —
пауза, команда не про музыку — вернуть, команда про музыку — оставить как есть.
"""

import ctypes
import logging
import queue
import threading
import time
from concurrent.futures import ThreadPoolExecutor

import media
import persona
from ai.provider import ASSISTANT, USER, Message, ProviderError
from ai.router import AIRouter
from commands import normalize
from memory import MemoryManager
from events import HEARD, LISTENING, NOTICE, THINKING, TIMEOUT, VOICE, Reply, StateEvent, Utterance
from executor import Executor, Response
from intent_router import CLOUD_DISABLED, LONG_COMMAND, TOO_LONG, UNSURE, IntentRouter, Route
from tools import NEEDS_CONFIRMATION, ToolManager

log = logging.getLogger("dialogue")

MUSIC_EFFECTS = {"music_on", "music_off", "music_launch", "music_close"}
IGNORED = "ignored"  # effect ответа: фраза пропущена, показывать нечего
YES = {"да", "ага", "угу", "давай", "конечно", "подтверждаю", "да давай"}
NO = {"нет", "не", "не надо", "отмена", "отмени", "нет не надо"}
CONFIRM_SECONDS = 10  # сколько ждать ответа «да / нет»


class VoiceSink:
    """Принимает события из VoiceListener (он вызывает put, как у очереди)."""

    def __init__(self, handler):
        self._handler = handler

    def put(self, event):
        self._handler(*event)


class DialogueManager:
    def __init__(self, config: dict, executor: Executor | None = None, ducker=None,
                 tools: ToolManager | None = None, router: IntentRouter | None = None,
                 ai: AIRouter | None = None, memory: MemoryManager | None = None,
                 clock=time.monotonic):
        self.config = config
        self.name = config.get("assistant_name", "Люся")
        self.executor = executor or Executor(config)
        self.tools = tools or ToolManager(self.executor)
        self.router = router or IntentRouter(config)
        self.ai = ai  # None — ни один ИИ-провайдер не подключён
        self.memory = memory or MemoryManager()
        self.system_prompt = persona.system_prompt(self.name)
        self._clock = clock
        # Что выполнить, если пользователь скажет «да», и до какого момента ждать
        self._pending: tuple[callable, float] | None = None
        # Вызывается, когда Люся задала вопрос и ждёт «да / нет» (слушатель ждёт ответ без имени)
        self.on_followup = None
        self.ducker = ducker if ducker is not None else (media.Ducker() if media.AVAILABLE else None)
        self.outbox: queue.Queue = queue.Queue()
        self.voice_sink = VoiceSink(self._on_voice)
        self._pool = ThreadPoolExecutor(max_workers=1, thread_name_prefix="dialogue")
        self._lock = threading.Lock()
        self._busy = False
        self._next_id = 0
        self._cancelled_up_to = 0  # ответы на запросы с номером не больше этого — устарели

    # --- Вход ----------------------------------------------------------------

    @property
    def busy(self) -> bool:
        with self._lock:
            return self._busy

    def submit(self, utterance: Utterance) -> int | None:
        """Принимает фразу в обработку. None — Люся занята предыдущей и фразу не взяла."""
        text = utterance.text.strip()
        with self._lock:
            if not text or self._busy:
                return None
            self._busy = True
            self._next_id += 1
            request_id = self._next_id
        self._pool.submit(self._process, request_id, utterance)
        return request_id

    def cancel_pending(self):
        """Ответы на уже отправленные запросы больше не нужны (будут отброшены)."""
        with self._lock:
            self._cancelled_up_to = self._next_id

    def shutdown(self):
        self._pool.shutdown(wait=False, cancel_futures=True)
        if self.ducker is not None:
            self.ducker.shutdown()

    def _on_voice(self, kind: str, text: str = "", *rest):
        """События речи (вызывается из потока распознавания)."""
        if kind == "wake":
            if self.busy:
                return
            if self.ducker is not None:
                self.ducker.duck()  # пауза музыке, чтобы лучше слышать команду
            self.outbox.put(StateEvent(LISTENING, text))  # text == "followup": ждёт ответ на вопрос
        elif kind == "partial":
            self.outbox.put(StateEvent(HEARD, text))
        elif kind == "command":
            confidence = rest[0] if rest else 1.0
            if self.submit(Utterance(text, source=VOICE, confidence=confidence)) is None and text.strip():
                # Люся ещё выполняет прошлую команду — не теряем новую молча
                self.outbox.put(StateEvent(NOTICE, "Секунду, я ещё занята прошлой командой. Повтори чуть позже."))
        elif kind == "timeout":
            if self.ducker is not None:
                self.ducker.unduck()
            self.outbox.put(StateEvent(TIMEOUT))
        elif kind in ("error", "notice"):
            self.outbox.put(StateEvent(NOTICE, text))

    # --- Обработка (в фоновом потоке) -------------------------------------------

    def _process(self, request_id: int, utterance: Utterance):
        self.outbox.put(StateEvent(THINKING))
        # COM нужен для os.startfile вне главного потока. Завершаем его в том же
        # потоке, если инициализация удалась (S_OK или S_FALSE — оба требуют CoUninitialize)
        hr = ctypes.windll.ole32.CoInitialize(None)
        try:
            response = self._handle(utterance)
        except Exception as e:  # чтобы Люся не зависла при неожиданной ошибке
            log.exception("ошибка обработки запроса")
            response = Response(f"Ой, ошибка: {e}", ok=False)
        finally:
            if hr >= 0:
                ctypes.windll.ole32.CoUninitialize()
            with self._lock:
                self._busy = False
                stale = request_id <= self._cancelled_up_to

        self._after_response(response)
        if stale:
            log.info("ответ на запрос %d отброшен как устаревший", request_id)
            return
        self.outbox.put(Reply(response.text, response.ok, response.effect, response.keep_running, request_id))
        if self._pending is not None and self.on_followup is not None:
            self.on_followup()  # Люся спросила «да?» — выслушать ответ без имени

    def _handle(self, utterance: Utterance) -> Response:
        # Ответ на вопрос Люси — только сразу после него и только «да» / «нет»
        pending, self._pending = self._pending, None
        if pending is not None and self._clock() <= pending[1]:
            answer = normalize(utterance.text)
            if answer in YES:
                return pending[0]()
            if answer in NO:
                return Response("Хорошо, не буду.")
            # другая фраза — вопрос снимается, фраза обрабатывается как обычно

        decision = self.router.decide(utterance)
        if decision.route is Route.IGNORE:
            return Response("", effect=IGNORED)
        if decision.route is Route.LOCAL:
            return self._run_command(decision.command)
        if decision.route is Route.CLOUD:
            return self._ask_ai(utterance)
        return self._clarify(decision.reason, utterance, decision.command)

    def _run_command(self, cmd) -> Response:
        call = self.tools.from_command(cmd)
        if call is None:  # помощь и выход — не действия с Windows
            return self.executor.execute(cmd)
        response = self.tools.call(call)
        if response.effect == NEEDS_CONFIRMATION:
            self._ask_yes(lambda: self.tools.call(call, confirmed=True))
        return response

    def _clarify(self, reason: str, utterance: Utterance, cmd) -> Response:
        heard = normalize(utterance.text)
        if reason == LONG_COMMAND:
            self._ask_yes(lambda: self._run_command(cmd))
            return Response(f"Ты сказал: «{heard}»? Скажи «да», если это мне.", ok=False)
        if reason == UNSURE:
            self._ask_yes(lambda: self._ask_ai(utterance))
            return Response(f"Ты сказал: «{heard}»? Скажи «да», и я спрошу у ИИ.", ok=False)
        if reason == TOO_LONG:
            return Response("Фраза длинная — не уверена, что это мне. Повтори покороче.", ok=False)
        if reason == CLOUD_DISABLED:
            return Response("Этого я пока не умею. Скажи «помощь», чтобы узнать, что я могу.", ok=False)
        return Response("Не поняла.", ok=False)

    def _ask_yes(self, action):
        """Запомнить, что сделать, если пользователь ответит «да»."""
        self._pending = (action, self._clock() + CONFIRM_SECONDS)

    def _ask_ai(self, utterance: Utterance) -> Response:
        if self.ai is None:
            return Response("ИИ пока не подключён.", ok=False)
        messages = self.memory.context() + [Message(USER, utterance.text)]
        try:
            result = self.ai.ask(messages, self.system_prompt)
        except ProviderError as e:
            return Response(e.user_message, ok=False)  # неудачный обмен в память не попадает
        self.memory.add(USER, utterance.text)
        self.memory.add(ASSISTANT, result.text)
        return Response(result.text)

    def _after_response(self, response: Response):
        """Музыка после команды: не про музыку — вернуть, про музыку — оставить как решила команда."""
        if self.ducker is None:
            return
        if response.effect in MUSIC_EFFECTS:
            self.ducker.forget()
        else:
            self.ducker.unduck()
