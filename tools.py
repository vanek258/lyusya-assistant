"""Каталог разрешённых действий и проверка каждого вызова.

Любое действие с Windows — и по локальной команде, и (в будущем) по
предложению ИИ — проходит через ToolManager.call():
  1. действие должно быть в каталоге;
  2. параметры проверяются (программы и сайты — только из config.json,
     музыка и громкость — только из разрешённых значений);
  3. действия высокого риска выполняются только после подтверждения.
Сами действия выполняет Executor — его код не меняется.
"""

from dataclasses import dataclass, field
from enum import IntEnum
from pathlib import Path

from commands import CLOSE, MEDIA, MUSIC, OPEN, VOLUME, Command
from executor import Executor, Response

NEEDS_CONFIRMATION = "needs_confirmation"  # effect ответа: нужно «да» от пользователя

# Файлы, открытие которых запускает программу или скрипт
EXECUTABLE_EXTENSIONS = {".exe", ".bat", ".cmd", ".com", ".msi", ".ps1", ".vbs", ".vbe",
                         ".js", ".jse", ".wsf", ".scr", ".lnk", ".reg", ".pif", ".hta", ".cpl"}

MEDIA_ACTIONS = {"play", "pause", "next", "prev"}
VOLUME_ACTIONS = {"up", "down", "mute"}


class Risk(IntEnum):
    LOW = 1      # открыть программу или сайт из списка, музыка, громкость
    MEDIUM = 2   # закрыть программу
    HIGH = 3     # запустить исполняемый файл — только с подтверждением


@dataclass
class ToolCall:
    name: str
    args: dict = field(default_factory=dict)


@dataclass(frozen=True)
class Tool:
    name: str
    risk: Risk
    description: str


TOOLS = {t.name: t for t in (
    Tool("open_site", Risk.LOW, "открыть сайт из списка"),
    Tool("open_app", Risk.LOW, "запустить программу из списка"),
    Tool("open_file", Risk.LOW, "открыть файл (исполняемый — высокий риск)"),
    Tool("close_app", Risk.MEDIUM, "закрыть окна программы из списка"),
    Tool("play_music", Risk.LOW, "включить музыку"),
    Tool("media", Risk.LOW, "пауза / играть / следующий / предыдущий трек"),
    Tool("volume", Risk.LOW, "громче / тише / без звука"),
)}


class ToolManager:
    def __init__(self, executor: Executor):
        self.executor = executor

    # --- Перевод локальной команды в вызов действия ---------------------------

    def from_command(self, cmd: Command) -> ToolCall | None:
        name = cmd.argument
        if cmd.intent == OPEN:
            if name in self.executor.site_aliases:
                return ToolCall("open_site", {"name": name})
            if name in self.executor.program_aliases:
                return ToolCall("open_app", {"name": name})
            return ToolCall("open_file", {"name": name})
        if cmd.intent == CLOSE:
            return ToolCall("close_app", {"name": name})
        if cmd.intent == MUSIC:
            return ToolCall("play_music")
        if cmd.intent == MEDIA:
            return ToolCall("media", {"action": name})
        if cmd.intent == VOLUME:
            return ToolCall("volume", {"action": name})
        return None

    # --- Выполнение с проверками --------------------------------------------------

    def call(self, call: ToolCall, confirmed: bool = False) -> Response:
        tool = TOOLS.get(call.name)
        if tool is None:
            return Response(f"Не знаю действия «{call.name}».", ok=False)
        if tool.risk is Risk.HIGH and not confirmed:
            return Response(f"Это действие нужно подтвердить: {tool.description}. Скажи «да».",
                            ok=False, effect=NEEDS_CONFIRMATION)
        handler = getattr(self, f"_{call.name}")
        return handler(call.args, confirmed)  # риск, зависящий от параметров, проверяет сам обработчик

    def _open_site(self, args, confirmed):
        name = args.get("name", "")
        if name not in self.executor.site_aliases:
            return Response(f"Сайта «{name}» нет в списке.", ok=False)
        return self.executor.execute(Command(OPEN, name))

    def _open_app(self, args, confirmed):
        name = args.get("name", "")
        if name not in self.executor.program_aliases:
            return Response(f"Программы «{name}» нет в списке.", ok=False)
        return self.executor.execute(Command(OPEN, name))

    def _open_file(self, args, confirmed):
        name = args.get("name", "")
        path = self._resolve_file(name)
        if path is None:
            return Response(f"Не нашла «{name}». Добавь его в config.json.", ok=False)
        if self.file_risk(path) is Risk.HIGH and not confirmed:
            return Response(f"«{path.name}» — это программа или скрипт. Точно запустить? Скажи «да».",
                            ok=False, effect=NEEDS_CONFIRMATION)
        return self.executor.execute(Command(OPEN, str(path)))

    def _close_app(self, args, confirmed):
        name = args.get("name", "")
        if name not in self.executor.program_aliases:
            return Response(f"Не знаю программу «{name}».", ok=False)
        return self.executor.execute(Command(CLOSE, name))

    def _play_music(self, args, confirmed):
        return self.executor.execute(Command(MUSIC))

    def _media(self, args, confirmed):
        action = args.get("action")
        if action not in MEDIA_ACTIONS:
            return Response("Не знаю такой команды для музыки.", ok=False)
        return self.executor.execute(Command(MEDIA, action))

    def _volume(self, args, confirmed):
        action = args.get("action")
        if action not in VOLUME_ACTIONS:
            return Response("Не знаю такой команды для громкости.", ok=False)
        return self.executor.execute(Command(VOLUME, action))

    # --- Вспомогательное --------------------------------------------------------

    def _resolve_file(self, name: str) -> Path | None:
        path = Path(name).expanduser()
        if path.exists():
            return path
        return self.executor._find_file(name)

    @staticmethod
    def file_risk(path: Path) -> Risk:
        return Risk.HIGH if path.suffix.lower() in EXECUTABLE_EXTENSIONS else Risk.LOW
