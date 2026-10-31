"""Общий интерфейс ИИ-провайдера.

Остальная программа знает только этот интерфейс: Message на входе,
AIResult на выходе и ошибки ProviderError. Всё, что специфично для
конкретного сервиса (Gemini, OpenAI, Claude, локальная модель), живёт
в его адаптере в ai/providers/ — и там же переводится в эти ошибки.
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass

USER = "user"
ASSISTANT = "assistant"


@dataclass(frozen=True)
class Message:
    role: str  # USER или ASSISTANT
    text: str


@dataclass(frozen=True)
class AIResult:
    text: str
    provider: str
    model: str = ""


class ProviderError(Exception):
    """Ошибка ИИ-провайдера. user_message можно показать пользователю как есть."""
    user_message = "ИИ вернул ошибку."


class AuthError(ProviderError):
    user_message = "Ключ ИИ не подошёл. Проверь его."


class QuotaError(ProviderError):
    user_message = "Лимит запросов к ИИ исчерпан."


class NetworkError(ProviderError):
    user_message = "Нет связи с ИИ. Локальные команды работают."


class ProviderTimeout(ProviderError):
    user_message = "ИИ не ответил вовремя."


class ModelUnavailable(ProviderError):
    user_message = "Модель ИИ сейчас недоступна."


class NoProviderAvailable(ProviderError):
    user_message = "ИИ сейчас недоступен. Локальные команды работают."


class DailyLimitReached(QuotaError):
    user_message = "На сегодня лимит запросов к ИИ исчерпан. Локальные команды работают."


class AIProvider(ABC):
    """Адаптер к одному ИИ-сервису."""

    name: str = ""

    @abstractmethod
    def available(self) -> bool:
        """Готов ли провайдер к работе (например, есть ли ключ). Без сетевых запросов."""

    @abstractmethod
    def generate(self, messages: list[Message], system: str, timeout: float) -> AIResult:
        """Ответ на разговор messages. Обязан уложиться в timeout секунд.

        Ошибки сервиса переводятся в подклассы ProviderError.
        """
