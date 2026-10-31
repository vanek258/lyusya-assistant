"""Управление плеерами через системные медиасессии Windows.

Это те же «сессии», что Windows показывает во всплывающем окне громкости:
у каждого плеера (Яндекс.Музыка, вкладка YouTube, Telegram) своя.
В отличие от медиаклавиш, так можно точно сказать, КОМУ «играть», а КОМУ
«пауза», и не включить случайно остановленное видео на YouTube.
"""

import asyncio
import logging
import threading
from concurrent.futures import ThreadPoolExecutor

log = logging.getLogger("media")

TIMEOUT = 5.0  # сколько секунд ждать ответа медиасессий Windows


class MediaTimeout(Exception):
    """Плеер не ответил вовремя: неизвестно, выполнилась операция или нет."""


try:
    from winrt.windows.media.control import (
        GlobalSystemMediaTransportControlsSessionManager as SessionManager,
        GlobalSystemMediaTransportControlsSessionPlaybackStatus as Status,
    )
    AVAILABLE = True
except ImportError:  # нет пакетов winrt — executor откатится на медиаклавиши
    AVAILABLE = False


def _run(make_coro, timeout: float = TIMEOUT):
    """Выполняет асинхронную функцию в отдельном потоке и ждёт результат.

    Отдельный поток нужен потому, что WinRT плохо работает в потоках,
    где COM уже инициализирован для os.startfile.

    Исход всегда однозначный: результат, исключение операции или MediaTimeout,
    если плеер не ответил за timeout секунд (тогда неизвестно, сработало ли).
    """
    result = {}

    def target():
        try:
            result["value"] = asyncio.run(make_coro())
        except Exception as e:
            result["error"] = e

    thread = threading.Thread(target=target, daemon=True)
    thread.start()
    thread.join(timeout)
    if thread.is_alive():
        raise MediaTimeout(f"медиасессии Windows не ответили за {timeout:.0f} с")
    if "error" in result:
        raise result["error"]
    return result["value"]


async def _sessions(app_id: str = ""):
    manager = await SessionManager.request_async()
    return [s for s in manager.get_sessions() if app_id.lower() in s.source_app_user_model_id.lower()]


def _is_playing(session) -> bool:
    return session.get_playback_info().playback_status == Status.PLAYING


def play(app_id: str) -> bool:
    """Включает воспроизведение в конкретном плеере. False — плеер не найден."""
    async def go():
        found = await _sessions(app_id)
        for s in found:
            await s.try_play_async()
        return bool(found)
    return _run(go)


def skip(app_id: str, forward: bool = True) -> bool:
    """Следующий/предыдущий трек в конкретном плеере. False — плеер не найден."""
    async def go():
        found = await _sessions(app_id)
        for s in found:
            await (s.try_skip_next_async() if forward else s.try_skip_previous_async())
        return bool(found)
    return _run(go)


def pause_playing() -> list[str]:
    """Ставит на паузу всё, что сейчас играет. Возвращает, кого остановили."""
    async def go():
        paused = []
        for s in await _sessions():
            if _is_playing(s):
                await s.try_pause_async()
                paused.append(s.source_app_user_model_id)
        return paused
    return _run(go)


def resume(app_ids: list[str]) -> None:
    """Снова включает плееры, которые остановила pause_playing()."""
    async def go():
        for s in await _sessions():
            if s.source_app_user_model_id in app_ids:
                await s.try_play_async()
    _run(go)


class Ducker:
    """Ставит музыку на паузу, пока Люся слушает команду, и потом возвращает её.

    Все операции выполняются по очереди в одном фоновом потоке, и только он
    трогает список остановленных плееров. Поэтому «пауза» и «продолжить» не могут
    перепутаться местами, даже если команда пришла раньше, чем закончилась пауза.
    """

    def __init__(self, pause=None, resume_fn=None):
        self._pause = pause or pause_playing
        self._resume = resume_fn or resume
        self._paused: list[str] = []
        self._pool = ThreadPoolExecutor(max_workers=1, thread_name_prefix="ducker")

    def duck(self):
        """Поставить на паузу всё, что играет (если ещё не стоит)."""
        return self._pool.submit(self._safe, self._do_duck)

    def unduck(self):
        """Вернуть то, что было поставлено на паузу."""
        return self._pool.submit(self._safe, self._do_unduck)

    def forget(self):
        """Забыть остановленные плееры — команда сама решила судьбу музыки."""
        return self._pool.submit(self._safe, self._do_forget)

    def shutdown(self):
        self._pool.shutdown(wait=False, cancel_futures=True)

    def _do_duck(self):
        if not self._paused:
            self._paused = list(self._pause())

    def _do_forget(self):
        self._paused = []

    def _do_unduck(self):
        ids, self._paused = self._paused, []
        if ids:
            self._resume(ids)

    @staticmethod
    def _safe(action):
        try:
            action()
        except Exception:  # недоступность плеера не должна ронять фоновый поток
            log.exception("ошибка управления медиасессиями")
