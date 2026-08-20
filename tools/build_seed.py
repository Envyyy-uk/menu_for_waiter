#!/usr/bin/env python3
"""Собирает `seed_menu.json` из каталога Menu-qr.

Источник — `data/menu.json` и `data/ui.json` того самого сайта, который
печатается в гостевом QR-меню. Здесь из него достаётся русская версия и
раскладывается в форму, понятную POS: подписи групп по-русски, обязательность
выбора, зависимости между группами и добавки.

    python3 tools/build_seed.py ../menu-qr > seed_menu.json

Названия позиций и брендов не переводятся: официант ищет их так, как
напечатано в меню, и так же они уходят на марку.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

RU = "ru"

# Группы, которые появляются, только если в другой группе выбрали своё.
# Спрашивать у официанта марку дарк-лифа, когда он выбрал сигарный лист,
# — это лишний тап на каждом кальяне.
DEPENDS: dict[tuple[str, str], dict[str, str]] = {
    ("hookah", "dark-leaf"): {"group": "leaf", "value": "dark-leaf"},
    ("hookah", "cigar-leaf"): {"group": "leaf", "value": "cigar-leaf"},
}

# Группы, которые можно пропустить. Всё остальное обязательно: «Мохито» без
# вкуса — это не заказ, а загадка для бармена.
OPTIONAL: set[tuple[str, str]] = {
    ("hookah", "fruit-head"),
    ("hookah", "extra"),
}

# Сколько добавок одной строкой имеет смысл заказать.
ADDON_MAX_QTY = 6


def ru(value: Any, fallback: str = "") -> str:
    """Русская строка из поля, которое бывает и строкой, и словарём языков."""
    if isinstance(value, dict):
        return value.get(RU) or value.get("en") or fallback
    return value if isinstance(value, str) else fallback


def build(src: Path) -> dict[str, Any]:
    menu = json.loads((src / "data" / "menu.json").read_text(encoding="utf-8"))
    ui = json.loads((src / "data" / "ui.json").read_text(encoding="utf-8"))

    def label(key: str | None) -> str:
        if not key:
            return ""
        return ru(ui.get(key), key)

    warnings = {k: ru(v) for k, v in menu.get("warnings", {}).items()}
    addons = menu.get("addons", {})

    categories = {c["key"]: ru(c["names"], c["key"]) for c in menu["categories"]}

    items: list[dict[str, Any]] = []
    for position, raw in enumerate(menu["items"]):
        key = raw["key"]

        groups: list[dict[str, Any]] = []
        for group in raw.get("options", []):
            gkey = group["key"]
            choices = []
            for choice in group["choices"]:
                out: dict[str, Any] = {
                    "key": choice["key"],
                    "name": ru(choice["name"], choice["key"]),
                }
                if choice.get("price_pence") is not None:
                    out["price_pence"] = int(choice["price_pence"])
                if choice.get("add_pence"):
                    out["add_pence"] = int(choice["add_pence"])
                choices.append(out)
            groups.append(
                {
                    "key": gkey,
                    "label": label(group.get("label")),
                    "mode": "one",
                    "required": (key, gkey) not in OPTIONAL,
                    "depends": DEPENDS.get((key, gkey)),
                    "add_pence": int(group.get("add_pence") or 0),
                    "choices": choices,
                }
            )

        # Добавки — отдельная группа с набором, а не переключателем: миксов к
        # бутылке берут два, и это одна строка чека, а не две.
        for addon_key in raw.get("add", []):
            addon = addons.get(addon_key)
            if addon is None:
                continue
            name = ru(addon["names"], addon_key)
            groups.append(
                {
                    "key": addon_key,
                    "label": name,
                    "mode": "many",
                    "required": False,
                    "depends": None,
                    "add_pence": 0,
                    "choices": [
                        {
                            "key": addon_key,
                            "name": name,
                            "add_pence": int(addon["price_pence"]),
                            "max_qty": ADDON_MAX_QTY,
                        }
                    ],
                }
            )

        warning_texts = [warnings[w] for w in raw.get("w", []) if w in warnings]

        items.append(
            {
                "key": key,
                "name": raw["name"],
                "description": ru(raw.get("desc")),
                "category": raw.get("category"),
                "station": raw.get("station", "bar"),
                "price_pence": int(raw.get("price_pence") or 0),
                "position": position,
                "state": "on",
                "options": groups,
                # Названия английские, а ищет официант по-русски.
                "search_terms": sorted({t.lower() for t in raw.get("alt", [])}),
                "warning": " ".join(warning_texts) or None,
            }
        )

    return {
        "_note": (
            "Собрано из каталога Menu-qr скриптом tools/build_seed.py. "
            "Названия позиций и брендов не переводятся: официант ищет их так, "
            "как напечатано в меню. Аллергенов нет намеренно — заведение их "
            "не предоставляло."
        ),
        "venue": {
            "key": menu["venue"]["key"],
            "name": menu["venue"].get("name") or "Заведение",
            "timezone": menu["venue"].get("timezone", "Europe/London"),
            "currency": menu["venue"].get("currency", "GBP"),
        },
        "categories": categories,
        "items": items,
    }


def main() -> None:
    src = Path(sys.argv[1] if len(sys.argv) > 1 else "../menu-qr")
    if not (src / "data" / "menu.json").exists():
        sys.exit(f"нет каталога меню: {src}/data/menu.json")
    json.dump(build(src), sys.stdout, ensure_ascii=False, indent=1)
    sys.stdout.write("\n")


if __name__ == "__main__":
    main()
