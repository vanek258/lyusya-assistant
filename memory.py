"""Память Люси.

Сейчас — только краткосрочная: последние реплики текущего разговора с ИИ,
чтобы второй вопрос понимался в контексте первого («найди ноутбук» →
«для программирования»). Хранится только в оперативной памяти, на диск не
пишется и забывается после паузы в разговоре.

Долговременная память (предпочтения, проекты, договорённости) — этап 7.
Здесь только её интерфейс, чтобы ядро диалога не пришлось переделывать.
"""

import time
from collections import deque
from typing import Protocol

from ai.provider import Message

MAX_MESSAGES = 10      # реплик в контексте (5 вопросов и 5 ответов)
IDLE_SECONDS = 300     # после 5 минут тишины разговор начинается заново


class LongTermMemory(Protocol):
    """Интерфейс долговременной памяти (реализация — этап 7)."""

    def remember(self, key: str, text: str) -> None: ...
    def recall(self, query: str) -> list[str]: ...
    def forget(self, key: str) -> None: ...


class MemoryManager:
    def __init__(self, max_messages: int = MAX_MESSAGES, idle_seconds: float = IDLE_SECONDS,
                 clock=time.monotonic, long_term: LongTermMemory | None = None):
        self._messages: deque[Message] = deque(maxlen=max_messages)
        self._idle_seconds = idle_seconds
        self._clock = clock
        self._last = clock()
        self.long_term = long_term

    def add(self, role: str, text: str) -> None:
        self._expire()
        self._messages.append(Message(role, text))
        self._last = self._clock()

    def context(self) -> list[Message]:
        """Реплики текущего разговора, от старых к новым."""
        self._expire()
        return list(self._messages)

    def clear(self) -> None:
        self._messages.clear()

    def _expire(self):
        if self._clock() - self._last > self._idle_seconds:
            self._messages.clear()
