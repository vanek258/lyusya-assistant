"""Низкоуровневые действия Windows: медиаклавиши, громкость, процессы."""

import ctypes
import subprocess

# Виртуальные коды медиаклавиш (те же, что на мультимедийной клавиатуре)
VK_MEDIA_NEXT_TRACK = 0xB0
VK_MEDIA_PREV_TRACK = 0xB1
VK_MEDIA_PLAY_PAUSE = 0xB3
VK_VOLUME_MUTE = 0xAD
VK_VOLUME_DOWN = 0xAE
VK_VOLUME_UP = 0xAF

# «Играть» и «пауза» — одна и та же клавиша-переключатель
MEDIA_KEYS = {
    "play": VK_MEDIA_PLAY_PAUSE,
    "pause": VK_MEDIA_PLAY_PAUSE,
    "next": VK_MEDIA_NEXT_TRACK,
    "prev": VK_MEDIA_PREV_TRACK,
}
VOLUME_KEYS = {"up": VK_VOLUME_UP, "down": VK_VOLUME_DOWN, "mute": VK_VOLUME_MUTE}

KEYEVENTF_EXTENDEDKEY = 0x1
KEYEVENTF_KEYUP = 0x2
CREATE_NO_WINDOW = 0x08000000  # не мигать консольным окном при вызове taskkill


def press_key(vk: int, times: int = 1) -> None:
    """Эмулирует нажатие клавиши (как будто нажали её на клавиатуре)."""
    for _ in range(times):
        ctypes.windll.user32.keybd_event(vk, 0, KEYEVENTF_EXTENDEDKEY, 0)
        ctypes.windll.user32.keybd_event(vk, 0, KEYEVENTF_EXTENDEDKEY | KEYEVENTF_KEYUP, 0)


def is_running(process: str) -> bool:
    """Проверяет, запущен ли процесс с таким именем (например, chrome.exe)."""
    result = subprocess.run(
        ["tasklist", "/FI", f"IMAGENAME eq {process}", "/NH"],
        capture_output=True, creationflags=CREATE_NO_WINDOW,
    )
    return process.lower().encode() in result.stdout.lower()


def close_process(process: str, force: bool = False) -> None:
    """Закрывает программу.

    Обычный режим просит окна закрыться (как крестик), поэтому браузер
    не будет потом ругаться «восстановить вкладки?». force — принудительно,
    нужно для программ, которые по крестику прячутся в трей (Discord).
    """
    args = ["taskkill", "/IM", process]
    if force:
        args += ["/F", "/T"]
    subprocess.run(args, capture_output=True, creationflags=CREATE_NO_WINDOW)
