#!/usr/bin/env python3
"""Звук сигнала «готово».

Рисуется кодом в WAV, а не берётся готовым файлом: так его слышно, из чего он
состоит, и его можно поменять одной строкой, не ища лицензию на чужой звук.

Три коротких тона подряд — их слышно сквозь шум зала и не спутать с
уведомлением мессенджера.

    python3 tools/make_sound.py
"""

from __future__ import annotations

import math
import struct
import wave
from pathlib import Path

OUT = Path(__file__).resolve().parents[1] / "frontend" / "assets" / "sound"
RATE = 44100


def tone(freq: float, seconds: float, volume: float = 0.55) -> list[float]:
    """Тон с мягкими краями: щелчок в начале звука режет ухо и на слух
    воспринимается как поломка, а не как сигнал."""
    total = int(RATE * seconds)
    edge = int(RATE * 0.006)
    out = []
    for n in range(total):
        # Пара обертонов: чистая синусоида на телефонном динамике почти
        # неслышна, а с ними сигнал пробивается сквозь разговор.
        value = (
            math.sin(2 * math.pi * freq * n / RATE)
            + 0.35 * math.sin(4 * math.pi * freq * n / RATE)
            + 0.12 * math.sin(6 * math.pi * freq * n / RATE)
        ) / 1.47
        if n < edge:
            value *= n / edge
        elif n > total - edge:
            value *= (total - n) / edge
        out.append(value * volume)
    return out


def silence(seconds: float) -> list[float]:
    return [0.0] * int(RATE * seconds)


def write(name: str, samples: list[float]) -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    with wave.open(str(OUT / name), "w") as f:
        f.setnchannels(1)
        f.setsampwidth(2)
        f.setframerate(RATE)
        f.writeframes(
            b"".join(struct.pack("<h", int(max(-1.0, min(1.0, s)) * 32767)) for s in samples)
        )


def main() -> None:
    # «Готово» — три восходящих тона. Официант должен узнать его с первого раза.
    ready = (
        tone(784, 0.13) + silence(0.05)
        + tone(988, 0.13) + silence(0.05)
        + tone(1319, 0.26)
        + silence(0.55)
    )
    write("ready.wav", ready)

    # Новая марка на станции — два коротких, ниже и спокойнее.
    write("arrived.wav", tone(660, 0.1) + silence(0.06) + tone(660, 0.14) + silence(0.3))

    # Тишина: ею «прогревается» звуковой канал после касания экрана, чтобы
    # первый настоящий сигнал не съелся политикой автозапуска.
    write("silence.wav", silence(0.25))

    print("звуки в", OUT)


if __name__ == "__main__":
    main()
