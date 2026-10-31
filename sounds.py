"""Короткие мягкие звуки. Синтезируются при запуске, файлы не нужны."""

import io
import math
import struct
import threading
import wave
import winsound

RATE = 22050


def _chime(notes, volume=0.2) -> bytes:
    """Собирает WAV из нот (частота, длительность) со звоном, как у колокольчика."""
    frames = bytearray()
    for freq, duration in notes:
        for i in range(int(RATE * duration)):
            t = i / RATE
            attack = min(1.0, i / (RATE * 0.004))       # мягкое начало без щелчка
            decay = math.exp(-t * 6 / duration)          # плавное затухание
            sample = math.sin(2 * math.pi * freq * t) + 0.3 * math.sin(4 * math.pi * freq * t)
            frames += struct.pack("<h", int(32767 * volume * attack * decay * sample / 1.3))
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(RATE)
        w.writeframes(bytes(frames))
    return buf.getvalue()


WAKE = _chime([(1046.5, 0.08), (1568.0, 0.16)])               # «динь-дилинь» вверх: слушаю
CANCEL = _chime([(784.0, 0.08), (523.3, 0.14)], volume=0.13)  # вниз, тише: не расслышала


def play(sound: bytes) -> None:
    """Проигрывает звук в фоне, не останавливая программу."""
    threading.Thread(target=winsound.PlaySound, args=(sound, winsound.SND_MEMORY), daemon=True).start()
