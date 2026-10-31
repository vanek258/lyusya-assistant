"""Низкоуровневые действия Windows: медиаклавиши, громкость, окна и процессы."""

import ctypes
import subprocess
from ctypes import wintypes
from pathlib import PureWindowsPath

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


WM_CLOSE = 0x0010
GW_OWNER = 4
# Окна самой Windows: рабочий стол и панель задач. «Закрыть» рабочий стол —
# значит вызвать диалог выключения компьютера, поэтому их не трогаем никогда.
SHELL_WINDOW_CLASSES = {"Progman", "WorkerW", "Shell_TrayWnd", "Shell_SecondaryTrayWnd"}
PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
_WNDENUMPROC = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)


def _process_name(pid: int) -> str:
    """Имя exe-файла процесса (например, chrome.exe) или "" если узнать нельзя."""
    kernel32 = ctypes.windll.kernel32
    handle = kernel32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
    if not handle:
        return ""
    try:
        buf = ctypes.create_unicode_buffer(1024)
        size = wintypes.DWORD(len(buf))
        if kernel32.QueryFullProcessImageNameW(handle, 0, buf, ctypes.byref(size)):
            return PureWindowsPath(buf.value).name
        return ""
    finally:
        kernel32.CloseHandle(handle)


def _window_class(hwnd) -> str:
    buf = ctypes.create_unicode_buffer(256)
    ctypes.windll.user32.GetClassNameW(hwnd, buf, len(buf))
    return buf.value


def main_windows(process: str) -> list[int]:
    """Видимые главные окна программы — те, что видны на панели задач.

    Скрытые и служебные окна, а также фоновые процессы без окон сюда не попадают.
    """
    user32 = ctypes.windll.user32
    found = []

    def callback(hwnd, _):
        if (user32.IsWindowVisible(hwnd) and not user32.GetWindow(hwnd, GW_OWNER)
                and user32.GetWindowTextLengthW(hwnd) > 0 and _window_class(hwnd) not in SHELL_WINDOW_CLASSES):
            pid = wintypes.DWORD()
            user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
            if _process_name(pid.value).lower() == process.lower():
                found.append(hwnd)
        return True

    user32.EnumWindows(_WNDENUMPROC(callback), 0)
    return found


def close_windows(windows: list[int]) -> None:
    """Просит окна закрыться — как нажатие на крестик.

    Программа сама решает, как закрываться: браузер сохранит вкладки,
    редактор спросит про несохранённые изменения.
    """
    for hwnd in windows:
        ctypes.windll.user32.PostMessageW(hwnd, WM_CLOSE, 0, 0)


def kill_process(process: str) -> None:
    """Принудительно завершает все процессы программы.

    Только для программ, у которых в config.json явно стоит force_close:
    например, Discord по крестику прячется в трей и иначе не закрывается.
    """
    subprocess.run(["taskkill", "/IM", process, "/F", "/T"], capture_output=True, creationflags=CREATE_NO_WINDOW)
