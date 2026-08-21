"""Каталог меню с сайта → позиции POS.

Здесь и только здесь живёт разбор каталога `Menu-qr`. Скрипт сборки
`tools/build_seed.py` и фоновая синхронизация зовут одну и ту же функцию —
иначе через полгода «микс к крепкому» считался бы по-разному в двух местах,
и разошлись бы они, как водится, на цене и при госте.

Из каталога берётся русская версия: интерфейс POS полностью русский, а
названия позиций и брендов не переводятся — официант ищет их так, как
напечатано в меню.
"""

from __future__ import annotations

from typing import Any

RU = "ru"

# Группы, которые появляются, только если в другой группе выбрали своё.
# Спрашивать марку дарк-лифа у того, кто взял сигарный лист, — это лишний тап
# на каждом кальяне.
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

# Из чего собираются миксы к крепкому: холодные безалкогольные напитки того же
# каталога. Горячее в стакан с виски не льют, а пиво миксом не бывает — оно
# отсекается по возрастному предупреждению, а не по списку названий.
MIXER_CATEGORIES = ("beer-soft",)


class CatalogueError(Exception):
    """Каталог получен, но им нельзя пользоваться."""


def ru(value: Any, fallback: str = "") -> str:
    """Русская строка из поля, которое бывает и строкой, и словарём языков."""
    if isinstance(value, dict):
        return value.get(RU) or value.get("en") or fallback
    return value if isinstance(value, str) else fallback


def mixer_choices(items: list[dict[str, Any]], price_pence: int) -> list[dict[str, Any]]:
    """Чем можно разбавить крепкое.

    «Микс» без названия напитка — это загадка для бармена ровно так же, как
    «Мохито» без вкуса. Поэтому выбор не абстрактный: официант называет
    конкретную колу или сок, и она попадает на марку.

    Список берётся из самого каталога, а не пишется руками: добавили на сайте
    новый сок — он появится и в миксах.
    """
    out: list[dict[str, Any]] = []
    for entry in items:
        if entry.get("category") not in MIXER_CATEGORIES:
            continue
        if any(str(w).endswith("age-check") for w in entry.get("w") or []):
            continue  # алкоголь миксом не бывает
        kinds = [g for g in entry.get("options") or [] if g.get("key") == "kind"]
        if kinds:
            for choice in kinds[0]["choices"]:
                out.append(
                    {
                        "key": f"{entry['key']}:{choice['key']}",
                        "name": ru(choice.get("name"), choice["key"]),
                        "add_pence": price_pence,
                        "max_qty": ADDON_MAX_QTY,
                    }
                )
        else:
            out.append(
                {
                    "key": entry["key"],
                    "name": entry.get("name") or entry["key"],
                    "add_pence": price_pence,
                    "max_qty": ADDON_MAX_QTY,
                }
            )
    return out


# Сколько добавок уходит в цену, когда берут бутылку.
FREE_WITH_BOTTLE = 2
BOTTLE_KEY = "bottle"


def _free_with_bottle(groups: list[dict[str, Any]]) -> dict[str, Any] | None:
    """«К бутылке два микса бесплатно», если у позиции вообще есть бутылка."""
    for group in groups:
        if any(c.get("key") == BOTTLE_KEY for c in group.get("choices") or []):
            return {"when": {group["key"]: BOTTLE_KEY}, "count": FREE_WITH_BOTTLE}
    return None


def _source_state(entry: dict[str, Any], soon_categories: set[str]) -> str:
    """Что сайт говорит про эту позицию.

    Три ответа, и они разные: «продаём», «скрыта» и «скоро». Последний — не
    придирка: раздел, помеченный на сайте «скоро», гость в меню видит, а
    заказать не может, и в зале должно быть так же.
    """
    if entry.get("state") not in (None, "available"):
        return "off"
    if entry.get("orderable") is False:
        return "off"
    if entry.get("category") in soon_categories:
        return "soon"
    return "on"


def convert(raw: dict[str, Any], ui: dict[str, Any] | None = None) -> dict[str, Any]:
    """Каталог сайта → то, что понимает POS.

    `ui` — словарь подписей того же сайта. Без него подписи групп берутся из
    запасного списка: он покрывает всё, что есть в каталоге сегодня, а
    незнакомый ключ показывается как есть — лучше «opt.foo», чем пустая
    строка над кнопками.
    """
    if not isinstance(raw, dict) or not isinstance(raw.get("items"), list):
        raise CatalogueError("это не каталог меню")
    if not raw["items"]:
        # Пустой каталог почти наверняка означает страницу ошибки, а не
        # заведение без меню. Обнулять по нему зал нельзя.
        raise CatalogueError("в каталоге нет позиций")

    labels = {**FALLBACK_LABELS, **{k: ru(v, k) for k, v in (ui or {}).items()}}

    def label(key: str | None) -> str:
        if not key:
            return ""
        return labels.get(key, key)

    warnings = {k: ru(v) for k, v in (raw.get("warnings") or {}).items()}
    addons = raw.get("addons") or {}
    categories = {c["key"]: ru(c.get("names"), c["key"]) for c in (raw.get("categories") or [])}

    # Категории меню, помеченного «скоро». Так на сайте выключают целый
    # раздел — например, кухню, — и в зале его продавать нельзя.
    soon_categories: set[str] = set()
    for menu in raw.get("menus") or []:
        if menu.get("soon"):
            soon_categories |= set(menu.get("categories") or [])

    items: list[dict[str, Any]] = []
    for position, entry in enumerate(raw["items"]):
        key = entry.get("key")
        if not key or not entry.get("name"):
            continue  # позиция без ключа или названия — не позиция

        groups: list[dict[str, Any]] = []
        for group in entry.get("options") or []:
            gkey = group.get("key")
            if not gkey or not group.get("choices"):
                continue
            choices = []
            for choice in group["choices"]:
                out: dict[str, Any] = {
                    "key": choice["key"],
                    "name": ru(choice.get("name"), choice["key"]),
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
        # бутылке берут два, и это одна строка чека, а не две. Причём миксы
        # разные: кола к одному стакану, сок к другому.
        for addon_key in entry.get("add") or []:
            addon = addons.get(addon_key)
            if addon is None:
                continue
            name = ru(addon.get("names"), addon_key)
            price = int(addon.get("price_pence") or 0)
            choices = mixer_choices(raw["items"], price)
            if not choices:
                # Каталог без безалкогольных напитков — оставляем добавку
                # безымянной, чтобы она не пропала совсем.
                choices = [
                    {"key": addon_key, "name": name, "add_pence": price, "max_qty": ADDON_MAX_QTY}
                ]
            groups.append(
                {
                    "key": addon_key,
                    "label": name,
                    "mode": "many",
                    "required": False,
                    "depends": None,
                    "add_pence": 0,
                    # На марке читается «Микс: Cola», а не просто «Cola»:
                    # бармен видит, что это разбавить, а не отдельный стакан.
                    "prefix": name,
                    # Правило заведения: к бутылке два микса в цене. Это
                    # условие на другой выбор, а не свойство самого микса,
                    # поэтому оно и записано условием — считать его в уме
                    # официант не должен, а спорить с гостем тем более.
                    "free": _free_with_bottle(groups),
                    "choices": choices,
                }
            )

        warning_texts = [warnings[w] for w in entry.get("w") or [] if w in warnings]

        items.append(
            {
                "key": key,
                "name": entry["name"],
                "description": ru(entry.get("desc")),
                "category": entry.get("category"),
                "station": entry.get("station") or "bar",
                "price_pence": int(entry.get("price_pence") or 0),
                "position": position,
                # Стоп с сайта. Позиция бывает скрыта поштучно
                # (`state: hidden`), а целое меню — помечено «скоро»
                # (`menus[].soon`): так на сайте выключена кухня. И то и
                # другое значит одно: гостю это сейчас не продают.
                "state": _source_state(entry, soon_categories),
                "options": groups,
                # Названия английские, а ищет официант по-русски.
                "search_terms": sorted({t.lower() for t in entry.get("alt") or []}),
                "warning": " ".join(warning_texts) or None,
            }
        )

    venue = raw.get("venue") or {}
    return {
        "venue": {
            "key": venue.get("key") or "venue",
            "name": venue.get("name") or "Заведение",
            "timezone": venue.get("timezone") or "Europe/London",
            "currency": venue.get("currency") or "GBP",
        },
        "categories": categories,
        "items": items,
    }


# Подписи групп на случай, когда словарь сайта недоступен: сеть могла отдать
# каталог и не отдать словарь, и из-за этого меню не должно остаться без
# подписей над кнопками выбора.
FALLBACK_LABELS = {
    "opt.size": "Объём",
    "opt.flavour": "Вкус",
    "opt.milk": "Молоко",
    "opt.kind": "Вид",
    "opt.style": "Стиль",
    "opt.leaf": "Лист",
    "opt.darkLeaf": "Дарк-лиф",
    "opt.cigarLeaf": "Сигарный лист",
    "opt.fruitHead": "Фруктовая чаша",
    "opt.extra": "Дополнительно",
}
