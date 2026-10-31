"""Поддельный провайдер для тестов: заданный ответ, заданная ошибка, задержка."""

import time

from ai.provider import AIProvider, AIResult, Message


class FakeProvider(AIProvider):
    def __init__(self, name: str = "fake", reply: str = "Ответ.", error: Exception | None = None,
                 delay: float = 0.0, is_available: bool = True):
        self.name = name
        self.reply = reply
        self.error = error
        self.delay = delay
        self.is_available = is_available
        self.calls: list[tuple[list[Message], str, float]] = []

    def available(self) -> bool:
        return self.is_available

    def generate(self, messages, system, timeout):
        self.calls.append((list(messages), system, timeout))
        if self.delay:
            time.sleep(self.delay)
        if self.error is not None:
            raise self.error
        return AIResult(self.reply, self.name, "fake-model")
