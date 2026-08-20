"""Цена позиции с вариантами.

Считает сервер, а не браузер. Иначе «бутылку по цене стопки» можно заказать,
подменив одну строку в запросе.

Правила, которые держат всю таблицу вариантов:

* `price_pence` у выбора **заменяет** цену позиции — 50 мл против бутылки;
* `add_pence` **прибавляется** — микс к крепкому, фруктовая чаша;
* группа с `depends` спрашивается, только когда в другой группе выбрали
  своё: марку дарк-лифа не спрашивают у того, кто взял сигарный лист;
* обязательную группу пропустить нельзя: «Мохито» без вкуса — это не заказ,
  а загадка для бармена.
"""

from __future__ import annotations

from typing import Any

from app.models import MenuItem


class PriceError(Exception):
    def __init__(self, message: str, status: int = 422, payload: dict[str, Any] | None = None):
        super().__init__(message)
        self.message = message
        self.status = status
        self.payload = payload or {}


Selection = dict[str, Any]  # {"size": "ml50", "mixer": ["mixer", "mixer"]}


def _group_active(group: dict[str, Any], chosen: Selection) -> bool:
    depends = group.get("depends")
    if not depends:
        return True
    return chosen.get(depends["group"]) == depends["value"]


def active_groups(item: MenuItem, chosen: Selection) -> list[dict[str, Any]]:
    """Группы, которые сейчас имеет смысл показывать и проверять."""
    return [g for g in (item.options or []) if _group_active(g, chosen)]


def resolve(item: MenuItem, chosen: Selection | None) -> tuple[int, list[str], Selection]:
    """→ (цена за единицу в пенсах, подписи для марки, нормализованный выбор).

    Нормализованный выбор возвращается затем, чтобы «повторить позицию»
    работало одним нажатием и не тащило за собой выбор из выключённой группы.
    """
    chosen = dict(chosen or {})
    groups = item.options or []
    by_key = {g["key"]: g for g in groups}

    unknown = set(chosen) - set(by_key)
    if unknown:
        raise PriceError(f"неизвестная группа: {', '.join(sorted(unknown))}")

    price = item.price_pence
    add = 0
    names: list[str] = []
    normalised: Selection = {}

    for group in groups:
        key = group["key"]
        if not _group_active(group, chosen):
            # Выбор из выключённой группы молча выбрасываем: он мог остаться
            # с прошлого нажатия, и платить за него никто не должен.
            continue

        picked = chosen.get(key)
        mode = group.get("mode", "one")
        choices = {c["key"]: c for c in group["choices"]}

        if mode == "many":
            picks = picked if isinstance(picked, list) else ([] if picked is None else [picked])
            counts: dict[str, int] = {}
            for pick in picks:
                if pick not in choices:
                    raise PriceError(f"неизвестный выбор: {key}={pick}")
                counts[pick] = counts.get(pick, 0) + 1
            if not counts:
                continue
            for pick, count in counts.items():
                choice = choices[pick]
                limit = int(choice.get("max_qty") or 1)
                if count > limit:
                    raise PriceError(f"{choice['name']}: больше {limit} нельзя")
                add += int(choice.get("add_pence") or 0) * count
                names.append(choice["name"] if count == 1 else f"{choice['name']} ×{count}")
            add += int(group.get("add_pence") or 0)
            normalised[key] = [p for p, c in counts.items() for _ in range(c)]
            continue

        if picked is None or picked == "":
            if group.get("required"):
                raise PriceError(
                    f"не выбрано: {group.get('label') or key}",
                    payload={"missing_option": key, "item": item.key},
                )
            continue
        if not isinstance(picked, str):
            raise PriceError(f"{key}: ожидается один выбор")
        choice = choices.get(picked)
        if choice is None:
            raise PriceError(f"неизвестный выбор: {key}={picked}")

        if choice.get("price_pence") is not None:
            price = int(choice["price_pence"])
        add += int(choice.get("add_pence") or 0)
        add += int(group.get("add_pence") or 0)
        names.append(choice["name"])
        normalised[key] = picked

    return price + add, names, normalised
