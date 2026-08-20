#!/usr/bin/env python3
"""Собирает `seed_menu.json` из каталога Menu-qr.

Это снимок на случай первого запуска без сети: обычно меню приезжает с сайта
само (`app/services/menu_sync.py`), и трогать этот файл руками не нужно.

Разбор каталога живёт в `backend/app/services/catalogue.py` и здесь только
вызывается — двух копий этой таблицы быть не должно, они разойдутся.

    python3 tools/build_seed.py ../menu-qr > seed_menu.json
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))

from app.services.catalogue import convert  # noqa: E402


def main() -> None:
    src = Path(sys.argv[1] if len(sys.argv) > 1 else "../menu-qr")
    menu_file = src / "data" / "menu.json"
    if not menu_file.exists():
        sys.exit(f"нет каталога меню: {menu_file}")

    raw = json.loads(menu_file.read_text(encoding="utf-8"))
    ui_file = src / "data" / "ui.json"
    ui = json.loads(ui_file.read_text(encoding="utf-8")) if ui_file.exists() else None

    payload = convert(raw, ui)
    payload["_note"] = (
        "Снимок каталога Menu-qr, собранный tools/build_seed.py. Нужен только "
        "для первого запуска без сети — дальше меню приезжает с сайта само."
    )
    json.dump(payload, sys.stdout, ensure_ascii=False, indent=1)
    sys.stdout.write("\n")


if __name__ == "__main__":
    main()
