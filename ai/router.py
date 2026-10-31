"""Выбор ИИ-провайдера для запроса.

Порядок провайдеров для каждого типа задачи берётся из config.json
(раздел ai.routing). AIRouter:
  • пропускает провайдеров, которые не настроены (нет ключа) или временно
    отключены после серии ошибок;
  • делает не больше одной попытки на провайдера — никаких бесконечных повторов;
  • переходит к резервному провайдеру, только если это разрешено
    (cloud.allow_fallback) — ведь это передача фразы ещё одному сервису;
  • следит за дневным лимитом запросов (cloud.daily_request_limit).
В журнал пишутся только имя провайдера и тип ошибки — не текст разговора.
"""

import logging
import time
from datetime import date

from ai.provider import AIProvider, AIResult, DailyLimitReached, Message, NoProviderAvailable, ProviderError
from config import cloud_settings

log = logging.getLogger("ai")

CHAT, COMPLEX, CODING = "chat", "complex", "coding"
DEFAULT_TIMEOUT = 20.0
FAILURES_BEFORE_COOLDOWN = 3
COOLDOWN_SECONDS = 60.0

CODING_WORDS = ("код", "python", "питон", "javascript", "функци", "программ", "ошибк", "баг", "скрипт")
COMPLEX_WORDS = ("объясни", "почему", "сравни", "план", "проанализируй", "разбери", "докажи")


class AIRouter:
    def __init__(self, config: dict, providers: dict[str, AIProvider], clock=time.monotonic, today=date.today):
        ai = config.get("ai", {})
        self.routing: dict[str, list[str]] = ai.get("routing", {})
        self.provider_settings: dict[str, dict] = ai.get("providers", {})
        cloud = cloud_settings(config)
        self.allow_fallback = cloud["allow_fallback"]
        self.daily_limit = cloud["daily_request_limit"]
        self.providers = providers
        self._clock = clock
        self._today = today
        self._failures: dict[str, int] = {}
        self._cooldown_until: dict[str, float] = {}
        self._count_day = None
        self._count = 0

    @staticmethod
    def classify(text: str) -> str:
        """Грубо определяет тип задачи по словам запроса."""
        lowered = text.lower()
        if any(w in lowered for w in CODING_WORDS):
            return CODING
        if any(w in lowered for w in COMPLEX_WORDS) or len(lowered.split()) > 15:
            return COMPLEX
        return CHAT

    def order_for(self, task: str) -> list[str]:
        order = self.routing.get(task) or self.routing.get(CHAT) or list(self.providers)
        return order if self.allow_fallback else order[:1]

    def ask(self, messages: list[Message], system: str = "") -> AIResult:
        task = self.classify(messages[-1].text) if messages else CHAT
        last_error: ProviderError | None = None
        for name in self.order_for(task):
            provider = self.providers.get(name)
            if provider is None or not provider.available() or self._cooling(name):
                continue
            self._use_daily_quota()
            timeout = float(self.provider_settings.get(name, {}).get("timeout", DEFAULT_TIMEOUT))
            try:
                result = provider.generate(messages, system, timeout)
            except ProviderError as e:
                log.warning("провайдер %s: %s", name, type(e).__name__)
                self._record_failure(name)
                last_error = e
                continue
            self._failures[name] = 0
            log.info("ответ от %s (задача: %s)", name, task)
            return result
        raise last_error or NoProviderAvailable()

    # --- Лимиты и временное отключение ------------------------------------------

    def _use_daily_quota(self):
        today = self._today()
        if today != self._count_day:
            self._count_day, self._count = today, 0
        if self._count >= self.daily_limit:
            raise DailyLimitReached()
        self._count += 1

    def _record_failure(self, name: str):
        self._failures[name] = self._failures.get(name, 0) + 1
        if self._failures[name] >= FAILURES_BEFORE_COOLDOWN:
            self._cooldown_until[name] = self._clock() + COOLDOWN_SECONDS
            self._failures[name] = 0
            log.warning("провайдер %s временно отключён на %.0f с", name, COOLDOWN_SECONDS)

    def _cooling(self, name: str) -> bool:
        return self._clock() < self._cooldown_until.get(name, 0.0)
