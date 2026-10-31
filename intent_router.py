"""Решает, что делать с фразой: выполнить локально, спросить ИИ, переспросить или пропустить.

Главные правила:
  • известная команда выполняется локально, облако не трогаем;
  • неизвестная фраза — не повод звонить в облако: облако должно быть включено
    пользователем, а сомнительная речь (короткая, неуверенно распознанная,
    слишком длинная) сначала переспрашивается.
"""

from dataclasses import dataclass
from enum import Enum

from commands import UNKNOWN, Command, normalize, parse
from config import cloud_settings
from events import TYPED, VOICE, Utterance


class Route(Enum):
    LOCAL = "local"      # выполнить известную команду
    CLOUD = "cloud"      # спросить ИИ
    CLARIFY = "clarify"  # переспросить или объяснить, что не умею
    IGNORE = "ignore"    # пропустить молча


# Причины для CLARIFY
CLOUD_DISABLED = "cloud_disabled"  # облако выключено — «этого я пока не умею»
UNSURE = "unsure"                  # короткая или неуверенно распознанная фраза
TOO_LONG = "too_long"              # длинная фраза — похоже на кусок видео или песни
LONG_COMMAND = "long_command"      # команда внутри длинной фразы — могла быть подслушана


@dataclass(frozen=True)
class Decision:
    route: Route
    command: Command | None = None
    reason: str = ""


class IntentRouter:
    def __init__(self, config: dict):
        self.name = config.get("assistant_name", "Люся")
        self.max_command_words = config.get("max_command_words", 6)
        self.cloud = cloud_settings(config)

    def decide(self, utterance: Utterance) -> Decision:
        cmd = parse(utterance.text, self.name)
        words = len(normalize(utterance.text).split())
        voice = utterance.source == VOICE

        if cmd.intent != UNKNOWN:
            if voice and words > self.max_command_words:
                return Decision(Route.CLARIFY, cmd, LONG_COMMAND)
            return Decision(Route.LOCAL, cmd)

        if voice and not utterance.wake_confirmed:
            return Decision(Route.IGNORE)
        if not self.cloud["enabled"]:
            return Decision(Route.CLARIFY, cmd, CLOUD_DISABLED)
        if utterance.source == TYPED:
            return Decision(Route.CLOUD, cmd)  # напечатали сами — сомнений нет
        if words > self.cloud["max_words"]:
            return Decision(Route.CLARIFY, cmd, TOO_LONG)
        if words <= 2 or utterance.confidence < self.cloud["min_confidence"]:
            return Decision(Route.CLARIFY, cmd, UNSURE)
        return Decision(Route.CLOUD, cmd)
