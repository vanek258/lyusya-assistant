"""Управление плеерами через системные медиасессии Windows.

Это те же «сессии», что Windows показывает во всплывающем окне громкости:
у каждого плеера (Яндекс.Музыка, вкладка YouTube, Telegram) своя.
В отличие от медиаклавиш, так можно точно сказать, КОМУ «играть», а КОМУ
«пауза», и не включить случайно остановленное видео на YouTube.
"""

import asyncio
import threading

try:
    from winrt.windows.media.control import (
        GlobalSystemMediaTransportControlsSessionManager as SessionManager,
        GlobalSystemMediaTransportControlsSessionPlaybackStatus as Status,
    )
    AVAILABLE = True
except ImportError:  # нет пакетов winrt — executor откатится на медиаклавиши
    AVAILABLE = False


def _run(make_coro):
    """Выполняет асинхронную функцию в отдельном потоке и ждёт результат.

    Отдельный поток нужен потому, что WinRT плохо работает в потоках,
    где COM уже инициализирован для os.startfile.
    """
    result = {}

    def target():
        try:
            result["value"] = asyncio.run(make_coro())
        except Exception as e:
            result["error"] = e

    thread = threading.Thread(target=target, daemon=True)
    thread.start()
    thread.join(5)
    if "error" in result:
        raise result["error"]
    return result.get("value")


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
    return _run(go) or []


def resume(app_ids: list[str]) -> None:
    """Снова включает плееры, которые остановила pause_playing()."""
    async def go():
        for s in await _sessions():
            if s.source_app_user_model_id in app_ids:
                await s.try_play_async()
    _run(go)
