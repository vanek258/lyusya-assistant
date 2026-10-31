"""Сообщения между ядром Люси и интерфейсом.

Ядро (DialogueManager) ничего не знает про окно: оно получает Utterance
и кладёт в свою исходящую очередь Reply и StateEvent. Интерфейс забирает
их из очереди в своём потоке и только показывает.
"""

from dataclasses import dataclass

# Источник фразы
VOICE = "voice"
TYPED = "typed"

# Состояния для StateEvent
LISTENING = "listening"  # услышала имя, ждёт команду
HEARD = "heard"          # промежуточный текст речи
THINKING = "thinking"    # обрабатывает запрос
TIMEOUT = "timeout"      # после имени ничего не сказали
NOTICE = "notice"        # служебное сообщение или ошибка подсистемы


@dataclass(frozen=True)
class Utterance:
    """Фраза пользователя.

    confidence — средняя уверенность распознавания (1.0 для напечатанного).
    wake_confirmed — было ли обращение по имени (для голоса).
    """
    text: str
    source: str = TYPED
    confidence: float = 1.0
    wake_confirmed: bool = True


@dataclass(frozen=True)
class Reply:
    """Ответ Люси. effect — подсказка для анимации (music_on, vol_up и т. д.)."""
    text: str
    ok: bool = True
    effect: str = ""
    keep_running: bool = True
    request_id: int = 0


@dataclass(frozen=True)
class StateEvent:
    """Изменение состояния, которое интерфейс показывает анимацией или репликой."""
    state: str
    text: str = ""
