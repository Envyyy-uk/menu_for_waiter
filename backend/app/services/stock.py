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

import uuid
from decimal import Decimal
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

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
    item.quantity = Decimal(str(item.quantity)) + amount
    return row


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


def _matches(recipe: Recipe, chosen: dict[str, Any]) -> bool:
    """Правило срабатывает, если совпал весь его выбор.

    Пустой выбор в правиле означает «на любой вариант»: пиво уходит с полки
    одинаково, что бы к нему ни выбрали.
    """
    for key, value in (recipe.options or {}).items():
        if chosen.get(key) != value:
            return False
    return True


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
        if not _matches(recipe, chosen):
            continue
        stock = db.get(StockItem, recipe.stock_item_id)
        if stock is None or not stock.active:
            continue
        amount = Decimal(str(recipe.per_unit)) * item.qty * sign
        if amount == 0:
            continue
        out.append(move(db, stock, amount, reason, user=user, check_item_id=item.id))
    return out


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
