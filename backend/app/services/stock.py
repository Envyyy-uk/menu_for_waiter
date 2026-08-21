"""Склад: сколько чего есть и куда оно делось.

Две вещи, на которых держится этот файл.

**Остаток — сумма движений, а не число, которое кто-то правит.** Иначе на
вопрос «куда делось полбутылки» ответить нечем. Пересчёт руками — тоже
движение, просто с причиной «инвентаризация».

**Списывается на отправке, а не на закрытии чека.** Позиция ушла на станцию —
её уже наливают, продукт израсходован; ждать закрытия чека значит весь вечер
видеть остаток, которого на полке давно нет. Отменили позицию — вернулось.
"""

from __future__ import annotations

import re
import uuid
from collections.abc import Iterable
from decimal import Decimal
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.permissions import can
from app.models import (
    MOVE_COUNT,
    MOVE_RETURN,
    MOVE_SALE,
    UNIT_NAMES,
    CheckItem,
    Recipe,
    StockItem,
    StockMove,
    User,
    utcnow,
)
from app.services import push, realtime


class StockError(Exception):
    def __init__(self, message: str, status: int = 400):
        super().__init__(message)
        self.message = message
        self.status = status


def move(
    db: Session,
    item: StockItem,
    delta: Decimal | float,
    reason: str,
    *,
    user: User | None = None,
    check_item_id: uuid.UUID | None = None,
    note: str | None = None,
) -> StockMove:
    """Одно движение по складу. Остаток пересчитывается тут же."""
    amount = Decimal(str(delta))
    row = StockMove(
        venue_id=item.venue_id,
        stock_item_id=item.id,
        delta=amount,
        reason=reason,
        by_id=user.id if user else None,
        check_item_id=check_item_id,
        note=(note or "").strip() or None,
        at=utcnow(),
    )
    db.add(row)
    before = _state_of(item)
    item.quantity = Decimal(str(item.quantity)) + amount
    after = _state_of(item)
    # Переход, а не состояние. Бутылка может весь вечер стоять в «мало» —
    # кричать об этом на каждую порцию значит научить не читать сообщения.
    row.crossed = after if after != before and after != "ok" else None
    return row


def _state_of(item: StockItem) -> str:
    quantity = float(item.quantity)
    low = float(item.low_at)
    return "out" if quantity <= 0 else ("low" if low and quantity <= low else "ok")


def count_to(db: Session, item: StockItem, actual: Decimal | float, user: User, note: str | None = None) -> StockMove:
    """Инвентаризация: записываем не новое число, а разницу.

    Так в журнале остаётся видно, сколько не сошлось, — а это и есть главный
    вопрос инвентаризации.
    """
    delta = Decimal(str(actual)) - Decimal(str(item.quantity))
    return move(db, item, delta, MOVE_COUNT, user=user, note=note)


def recipes_for(db: Session, menu_item_id) -> list[Recipe]:
    return list(
        db.scalars(select(Recipe).where(Recipe.menu_item_id == menu_item_id)).all()
    )


def _factor(recipe: Recipe, chosen: dict[str, Any]) -> int:
    """Сколько раз сработало правило. Ноль — не сработало.

    Пустой выбор в правиле означает «на любой вариант»: пиво уходит с полки
    одинаково, что бы к нему ни выбрали.

    Отдельный случай — группа с несколькими выборами, то есть микс. Там
    выбранное лежит списком, и «Cola» может стоять в нём дважды: гость взял
    водку с двумя колами. Сравнивать список со строкой бессмысленно —
    считаем, сколько раз выбран напиток, и столько банок и уходит.
    """
    factor = 1
    for key, value in (recipe.options or {}).items():
        got = chosen.get(key)
        if isinstance(got, list):
            count = sum(1 for x in got if x == value)
            if not count:
                return 0
            factor *= count
        elif got != value:
            return 0
    return factor


VOLUME = re.compile(r"(\d+(?:[.,]\d+)?)")


def volume_of(chosen: dict[str, Any]) -> Decimal | None:
    """Сколько миллилитров выбрал официант.

    Ключ варианта и есть ответ: `ml50` — пятьдесят. Там, где объёма нет
    («бутылка»), возвращается None: сколько в бутылке, знает только правило.
    """
    for value in chosen.values():
        if not isinstance(value, str) or not value.startswith("ml"):
            continue
        found = VOLUME.search(value)
        if found:
            return Decimal(found.group(1).replace(",", "."))
    return None


def _amount(recipe: Recipe, chosen: dict[str, Any]) -> Decimal:
    """Сколько уходит с полки на одну проданную позицию."""
    if recipe.by_volume:
        volume = volume_of(chosen)
        # Объёма в выборе нет — значит взяли бутылку целиком, а её размер
        # записан в самом правиле.
        return volume if volume is not None else Decimal(str(recipe.per_unit))
    return Decimal(str(recipe.per_unit))


def needed(db: Session, rows: Iterable[CheckItem]) -> dict[uuid.UUID, Decimal]:
    """Сколько продукта нужно на эти позиции чека.

    Считается по тем же правилам, по которым потом списывается: иначе запрет
    и списание разойдутся, и официант останется с чеком, который нельзя
    отправить, но который уже уменьшил остаток.
    """
    want: dict[uuid.UUID, Decimal] = {}
    for item in rows:
        if item.menu_item_id is None:
            continue
        chosen = dict(item.options_keys or {})
        for recipe in recipes_for(db, item.menu_item_id):
            factor = _factor(recipe, chosen)
            if not factor:
                continue
            amount = _amount(recipe, chosen) * item.qty * factor
            if amount <= 0:
                continue
            want[recipe.stock_item_id] = want.get(recipe.stock_item_id, Decimal(0)) + amount
    return want


def shortages(db: Session, rows: Iterable[CheckItem]) -> list[dict[str, Any]]:
    """Чего не хватит, если это отправить.

    Позиция без правила не ограничена ничем: склад знает не про всё, и
    запрещать продавать то, чего он не считает, значит останавливать зал
    из-за пробела в учёте.
    """
    out: list[dict[str, Any]] = []
    for stock_id, want in needed(db, rows).items():
        item = db.get(StockItem, stock_id)
        if item is None or not item.active:
            continue
        have = Decimal(str(item.quantity))
        if want > have:
            out.append(
                {
                    "name": item.name,
                    "unit_name": UNIT_NAMES.get(item.unit, item.unit),
                    "need": float(want),
                    "have": float(max(Decimal(0), have)),
                }
            )
    return out


def shortage_text(rows: list[dict[str, Any]]) -> str:
    """«Absolut: нужно 150 мл, на складе 100 мл» — так это читают."""
    return "Не хватает на складе. " + "; ".join(
        f"{r['name']}: нужно {_num(r['need'])} {r['unit_name']}, "
        f"есть {_num(r['have'])} {r['unit_name']}"
        for r in rows
    )


def _num(value: float) -> str:
    return str(int(value)) if float(value).is_integer() else str(value)


def alarms(db: Session, ids: Iterable[uuid.UUID]) -> list[dict[str, Any]]:
    """Что из тронутого ушло в «мало» или «кончилось».

    Нужно, чтобы сказать об этом сразу, а не когда админ сам заглянет на
    склад: бутылка кончается посреди вечера, а не в конце месяца.
    """
    out: list[dict[str, Any]] = []
    for stock_id in set(ids):
        item = db.get(StockItem, stock_id)
        if item is None or not item.active:
            continue
        payload = item_payload(item)
        if payload["state"] != "ok":
            out.append(payload)
    return out


def consume(db: Session, item: CheckItem, user: User | None = None) -> list[StockMove]:
    """Списать со склада то, что ушло на станцию."""
    return _apply(db, item, MOVE_SALE, -1, user)


def give_back(db: Session, item: CheckItem, user: User | None = None) -> list[StockMove]:
    """Вернуть на склад отменённую позицию."""
    return _apply(db, item, MOVE_RETURN, 1, user)


def _apply(db: Session, item: CheckItem, reason: str, sign: int, user: User | None) -> list[StockMove]:
    if item.menu_item_id is None:
        return []
    chosen = dict(item.options_keys or {})
    out: list[StockMove] = []
    for recipe in recipes_for(db, item.menu_item_id):
        factor = _factor(recipe, chosen)
        if not factor:
            continue
        stock = db.get(StockItem, recipe.stock_item_id)
        if stock is None or not stock.active:
            continue
        amount = _amount(recipe, chosen) * item.qty * factor * sign
        if amount == 0:
            continue
        out.append(move(db, stock, amount, reason, user=user, check_item_id=item.id))
    return out


def announce(db: Session, venue_id, moves: Iterable[StockMove]) -> None:
    """Сказать о складе тем, кто за него отвечает.

    Два адреса и разные поводы. В сокет уходит любое движение — экран склада
    должен обновляться сам, без перезагрузки страницы. Push уходит только на
    переход в «мало» или «кончилось»: уведомление на каждую порцию учит не
    читать уведомления.

    Зовётся после `commit`: до него изменений ещё нет, и экран, прибежавший
    за свежими данными, увидел бы старые.
    """
    moves = list(moves)
    if not moves:
        return

    realtime.publish(
        realtime.CHANNEL_STOCK,
        {"type": "stock.changed"},
    )

    crossed = [m for m in moves if getattr(m, "crossed", None)]
    if not crossed:
        return

    names = {}
    for m in crossed:
        item = db.get(StockItem, m.stock_item_id)
        if item is not None:
            names[item.name] = m.crossed

    out = [n for n, s in names.items() if s == "out"]
    low = [n for n, s in names.items() if s == "low"]
    if not out and not low:
        return

    title = "Кончилось" if out else "Заканчивается"
    body = ", ".join(out or low)
    realtime.publish(
        realtime.CHANNEL_STOCK,
        {"type": "stock.low", "out": out, "low": low, "title": title, "body": body},
    )

    # Push — тем, кто отвечает за склад. Владелец может не смотреть в
    # админку весь вечер, а бутылка кончается в середине.
    watchers = db.scalars(
        select(User).where(User.venue_id == venue_id, User.active.is_(True))
    ).all()
    for user in watchers:
        if can(user.role, "stock.view"):
            push.notify(
                user.id,
                {"title": title, "body": body, "tag": "stock", "url": "/admin/"},
            )


# --------------------------------------------------------------- ответы ---
def item_payload(item: StockItem) -> dict[str, Any]:
    quantity = float(item.quantity)
    low = float(item.low_at)
    return {
        "id": str(item.id),
        "name": item.name,
        "unit": item.unit,
        "unit_name": UNIT_NAMES.get(item.unit, item.unit),
        "quantity": quantity,
        "low_at": low,
        # Три состояния, а не два: «кончилось» и «мало» — разные новости.
        "state": "out" if quantity <= 0 else ("low" if low and quantity <= low else "ok"),
        "note": item.note,
        "active": item.active,
    }
