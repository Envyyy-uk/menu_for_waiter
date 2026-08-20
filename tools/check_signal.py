#!/usr/bin/env python3
"""Прогон сигнала «готово» в настоящем браузере.

Это главное обещание системы, и проверять его на словах нельзя. Здесь
смотрим на то, что реально произошло в браузере официанта: заиграла ли
дорожка, повторяется ли сигнал, гаснет ли он после «Забрал» и переживает ли
он обрыв связи.

Браузер запускается с разрешённым автозапуском звука — иначе в headless
проверить воспроизведение нечем. В жизни это разрешение даёт первое касание
экрана, и оно приходит на вводе PIN.

    python3 tools/check_signal.py [http://127.0.0.1:8000]
"""

from __future__ import annotations

import sys
from pathlib import Path

from playwright.sync_api import sync_playwright

CHROME = next(
    (str(p) for p in sorted(Path("/opt/pw-browsers").glob("chromium*/chrome-linux/chrome"))),
    None,
)
BASE = sys.argv[1] if len(sys.argv) > 1 else "http://127.0.0.1:8000"
PHONE = {"width": 390, "height": 844}
TABLET = {"width": 1180, "height": 820}

fails: list[str] = []


def check(name: str, ok: bool, detail: str = "") -> None:
    print(("  ok  " if ok else " FAIL ") + name + (f" — {detail}" if detail and not ok else ""))
    if not ok:
        fails.append(name)


def pin(page, code: str) -> None:
    for digit in code:
        page.get_by_role("button", name=digit, exact=True).click()
    page.wait_for_timeout(1000)


# Считаем настоящие проигрывания: подменяем не сигнал, а только счётчик.
SPY = """
// Скрипт вставляется в каждый документ до его собственных скриптов.
// Это обычные инструкции, а не функция: стрелочное выражение здесь только
// вычислилось бы и никогда не вызвалось.
window.__played = [];
(function spyOnPlayback() {
  const real = HTMLMediaElement.prototype.play;
  HTMLMediaElement.prototype.play = function () {
    // Счётчик никогда не роняет воспроизведение: тот, что ломает то, что
    // считает, хуже отсутствия счётчика.
    try {
      if (this.volume > 0) {
        (window.__played = window.__played || []).push(this.currentSrc || this.src);
      }
    } catch (e) { /* не посчитали — играть всё равно надо */ }
    return real.apply(this, arguments);
  };
})();
"""


def main() -> None:
    with sync_playwright() as pw:
        browser = pw.chromium.launch(
            executable_path=CHROME,
            args=["--autoplay-policy=no-user-gesture-required"],
        )

        waiter_ctx = browser.new_context(viewport=PHONE, has_touch=True, is_mobile=True)
        waiter = waiter_ctx.new_page()
        errors: list[str] = []
        waiter.on("pageerror", lambda e: errors.append(str(e)))
        waiter.add_init_script(SPY)
        waiter.goto(BASE, wait_until="networkidle")
        pin(waiter, "1111")

        check("дорожка сигнала загружена",
              waiter.evaluate("() => !!Sound.tracks.ready"))
        check("звук объявлен воспроизведением, а не уведомлением",
              waiter.evaluate("() => !navigator.audioSession || navigator.audioSession.type === 'playback'"))

        bar_ctx = browser.new_context(viewport=TABLET, has_touch=True)
        bar = bar_ctx.new_page()
        bar.goto(BASE + "/station/", wait_until="networkidle")
        pin(bar, "2222")

        # Официант отправляет заказ.
        waiter.locator(".tile:not(.busy)").first.click()
        waiter.wait_for_timeout(400)
        waiter.get_by_role("button", name="Открыть стол").click()
        waiter.wait_for_timeout(900)
        waiter.locator(".search input").fill("мохито")
        waiter.wait_for_timeout(400)
        waiter.locator(".dish").first.click()
        waiter.wait_for_timeout(500)
        waiter.get_by_role("button", name="К чеку").click()
        waiter.wait_for_timeout(400)
        waiter.get_by_role("button", name="Отправить").click()
        waiter.wait_for_timeout(1200)

        waiter.evaluate("() => { window.__played = []; }")

        # Бармен отдаёт.
        bar.wait_for_selector(".mark", timeout=6000)
        bar.locator(".mark").last.get_by_role("button", name="Готово").click()

        waiter.wait_for_function("() => (window.__played || []).length > 0", timeout=6000)
        played = waiter.evaluate("() => window.__played || []")
        check("сигнал заиграл", any("ready.wav" in p for p in played), str(played))
        check("сигнал идёт через <audio>, то есть по медиаканалу",
              waiter.evaluate("() => Sound.tracks.ready instanceof HTMLAudioElement"))
        check("сигнал повторяется, пока не забрали",
              waiter.evaluate("() => Sound.timer !== null"))

        # Ждём повтор — пропущенное уведомление хуже лишнего.
        waiter.evaluate("() => { window.__played = []; }")
        waiter.wait_for_timeout(5000)
        check("повтор пришёл сам",
              waiter.evaluate("() => (window.__played || []).length") >= 1,
              str(waiter.evaluate("() => window.__played || []")))

        waiter.get_by_role("button", name="Забрал").first.click()
        waiter.wait_for_timeout(1500)
        check("после «Забрал» сигнал замолчал",
              waiter.evaluate("() => Sound.timer === null"))

        # Сокет оборвался, событие потеряно — сигнал всё равно должен ожить.
        waiter.get_by_role("button", name="←").click()
        waiter.wait_for_timeout(600)
        waiter.locator(".tile.busy").first.click()
        waiter.wait_for_timeout(600)
        if waiter.locator(".sheet").count():
            waiter.locator(".sheet .btn").first.click()
            waiter.wait_for_timeout(600)
        waiter.get_by_role("button", name="Меню").click()
        waiter.wait_for_timeout(600)
        waiter.locator(".search input").fill("мохито")
        waiter.wait_for_timeout(400)
        waiter.locator(".dish").first.click()
        waiter.wait_for_timeout(500)
        waiter.get_by_role("button", name="К чеку").click()
        waiter.wait_for_timeout(400)
        waiter.get_by_role("button", name="Отправить").click()
        waiter.wait_for_timeout(1200)

        waiter_ctx.set_offline(True)
        waiter.wait_for_timeout(1500)
        bar.wait_for_selector(".mark", timeout=6000)
        bar.locator(".mark").last.get_by_role("button", name="Готово").click()
        bar.wait_for_timeout(1000)
        waiter.evaluate("() => { window.__played = []; }")
        waiter_ctx.set_offline(False)
        waiter.wait_for_function("() => (window.__played || []).length > 0", timeout=15000)
        check("пропущенный сигнал догоняет после обрыва связи",
              waiter.evaluate("() => Sound.timer !== null"))

        check("ошибок в консоли нет", not errors, "; ".join(errors[:3]))
        browser.close()

    print()
    if fails:
        print("не прошло:", ", ".join(fails))
        sys.exit(1)
    print("сигнал работает")


if __name__ == "__main__":
    main()
