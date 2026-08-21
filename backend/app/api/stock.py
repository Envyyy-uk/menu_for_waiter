"""Склад: остатки, движения и рецепты.

Доступ только у владельца и администратора: остаток на полке — это деньги,
и правит его тот, кто за них отвечает.
"""

from __future__ import annotations

import uuid
from decimal import Decimal

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session as DbSession

from app.core.deps import get_venue, require
from app.db import get_db
from app.models import (
    MOVE_IN,
    MOVE_NAMES,
    MOVE_REASONS,
    MOVE_WRITE_OFF,
    UNIT_NAMES,
    UNITS,
    MenuItem,
    Recipe,
    StockItem,
    StockMove,
    User,
    Venue,
)
from app.services import realtime, stock
from app.services.audit import record

router = APIRouter(prefix="/api/stock", tags=["склад"])


def _item(db: DbSession, venue: Venue, item_id: uuid.UUID) -> StockItem:
    row = db.get(StockItem, item_id)
    if row is None or row.venue_id != venue.id:
        raise HTTPException(status_code=404, detail="позиции склада нет")
    return row


@router.get("")
def listing(
    actor: User = Depends(require("stock.view")),
    db: DbSession = Depends(get_db),
    venue: Venue = Depends(get_venue),
) -> dict:
    rows = db.scalars(
        select(StockItem).where(StockItem.venue_id == venue.id).order_by(StockItem.name)
    ).all()
    items = [stock.item_payload(i) for i in rows if i.active]
    return {
        "units": [{"key": u, "name": UNIT_NAMES[u]} for u in UNITS],
        "items": items,
        # Сводка вперёд списка: ради неё склад и открывают.
        "out": [i["name"] for i in items if i["state"] == "out"],
        "low": [i["name"] for i in items if i["state"] == "low"],
    }


class ItemIn(BaseModel):
    name: str = Field(min_length=1, max_length=160)
    unit: str = "pc"
    quantity: float = 0
    low_at: float = 0
    note: str | None = None


@router.post("", status_code=201)
def create(
    body: ItemIn,
    actor: User = Depends(require("stock.edit")),
    db: DbSession = Depends(get_db),
    venue: Venue = Depends(get_venue),
) -> dict:
    if body.unit not in UNITS:
        raise HTTPException(status_code=422, detail="неизвестная единица")
    twin = db.scalars(
        select(StockItem).where(StockItem.venue_id == venue.id, StockItem.name == body.name.strip())
    ).first()
    if twin is not None:
        raise HTTPException(status_code=409, detail="такая позиция уже есть")

    item = StockItem(
        venue_id=venue.id,
        name=body.name.strip(),
        unit=body.unit,
        low_at=Decimal(str(body.low_at)),
        note=(body.note or "").strip() or None,
        quantity=0,
    )
    db.add(item)
    db.flush()
    moves = []
    if body.quantity:
        # Стартовый остаток — это приход, а не «просто число»: иначе первая
        # же сверка не сойдётся и объяснить будет нечем.
        moves.append(
            stock.move(db, item, Decimal(str(body.quantity)), MOVE_IN, user=actor,
                       note="стартовый остаток")
        )
    db.commit()
    stock.announce(db, venue.id, moves)
    return stock.item_payload(item)


class ItemPatch(BaseModel):
    name: str | None = None
    low_at: float | None = None
    note: str | None = None
    active: bool | None = None


@router.patch("/{item_id}")
def edit(
    item_id: uuid.UUID,
    body: ItemPatch,
    actor: User = Depends(require("stock.edit")),
    db: DbSession = Depends(get_db),
    venue: Venue = Depends(get_venue),
) -> dict:
    item = _item(db, venue, item_id)
    if body.name is not None:
        item.name = body.name.strip()
    if body.low_at is not None:
        item.low_at = Decimal(str(body.low_at))
    if body.note is not None:
        item.note = body.note.strip() or None
    if body.active is not None:
        item.active = body.active
    db.commit()
    # Порог мог поменяться — экран склада должен показать это сам.
    realtime.publish(realtime.CHANNEL_STOCK, {"type": "stock.changed"})
    return stock.item_payload(item)


class MoveIn(BaseModel):
    delta: float | None = None
    # Инвентаризация присылает не разницу, а то, что насчитали на полке.
    counted: float | None = None
    reason: str = MOVE_IN
    note: str | None = None


@router.post("/{item_id}/move")
def register(
    item_id: uuid.UUID,
    body: MoveIn,
    actor: User = Depends(require("stock.edit")),
    db: DbSession = Depends(get_db),
    venue: Venue = Depends(get_venue),
) -> dict:
    """Приход, списание или пересчёт.

    Продажи сюда не приходят: их пишет сам зал, когда позиция уходит на
    станцию.
    """
    item = _item(db, venue, item_id)
    if body.reason not in MOVE_REASONS:
        raise HTTPException(status_code=422, detail="неизвестная причина")

    if body.counted is not None:
        row = stock.count_to(db, item, body.counted, actor, body.note)
    else:
        if not body.delta:
            raise HTTPException(status_code=422, detail="ноль двигать незачем")
        delta = abs(body.delta) if body.reason == MOVE_IN else body.delta
        if body.reason == MOVE_WRITE_OFF:
            delta = -abs(body.delta)
        row = stock.move(db, item, delta, body.reason, user=actor, note=body.note)

    record.write(
        db,
        venue_id=venue.id,
        user_id=actor.id,
        action="stock.move",
        entity=f"stock:{item.name}",
        after={"delta": float(row.delta), "reason": body.reason, "note": body.note},
    )
    db.commit()
    stock.announce(db, venue.id, [row])
    return stock.item_payload(item)


@router.get("/{item_id}/moves")
def moves(
    item_id: uuid.UUID,
    limit: int = Query(default=50, ge=1, le=200),
    actor: User = Depends(require("stock.view")),
    db: DbSession = Depends(get_db),
    venue: Venue = Depends(get_venue),
) -> list[dict]:
    item = _item(db, venue, item_id)
    rows = db.scalars(
        select(StockMove)
        .where(StockMove.stock_item_id == item.id)
        .order_by(StockMove.at.desc())
        .limit(limit)
    ).all()
    names = {u.id: u.name for u in db.scalars(select(User).where(User.venue_id == venue.id)).all()}
    return [
        {
            "at": m.at.isoformat(),
            "delta": float(m.delta),
            "reason": m.reason,
            "reason_name": MOVE_NAMES.get(m.reason, m.reason),
            # У продажи имя тоже есть: её записывает тот, кто отправил заказ.
            "who": names.get(m.by_id, "—"),
            "note": m.note,
        }
        for m in rows
    ]


# ------------------------------------------------------------- рецепты ----
class RecipeIn(BaseModel):
    menu_item_id: uuid.UUID
    stock_item_id: uuid.UUID
    per_unit: float = Field(gt=0)
    # {"size": "ml50"} — правило только для этого варианта; пусто — для любого.
    options: dict = Field(default_factory=dict)


def _variant_text(item: MenuItem | None, chosen: dict) -> str:
    """«Объём: 50 мл» вместо «size: ml50».

    Ключи нужны машине, человеку нужны названия — а правило списания читают
    глазами, сверяя с бутылкой на полке.
    """
    if not chosen:
        return ""
    groups = {g["key"]: g for g in ((item.options if item else None) or [])}
    parts = []
    for key, value in chosen.items():
        group = groups.get(key)
        if group is None:
            parts.append(f"{key}: {value}")
            continue
        choice = next((c for c in group["choices"] if c["key"] == value), None)
        parts.append(f"{group.get('label') or key}: {choice['name'] if choice else value}")
    return " · ".join(parts)


@router.get("/recipes")
def recipes(
    actor: User = Depends(require("stock.view")),
    db: DbSession = Depends(get_db),
    venue: Venue = Depends(get_venue),
) -> list[dict]:
    rows = db.scalars(select(Recipe).where(Recipe.venue_id == venue.id)).all()
    menu = {
        i.id: i for i in db.scalars(select(MenuItem).where(MenuItem.venue_id == venue.id)).all()
    }
    goods = {
        i.id: i for i in db.scalars(select(StockItem).where(StockItem.venue_id == venue.id)).all()
    }
    return [
        {
            "id": str(r.id),
            "menu_item_id": str(r.menu_item_id),
            "menu_item": menu[r.menu_item_id].name if r.menu_item_id in menu else "—",
            "stock_item_id": str(r.stock_item_id),
            "stock_item": goods[r.stock_item_id].name if r.stock_item_id in goods else "—",
            "unit_name": UNIT_NAMES.get(goods[r.stock_item_id].unit, "")
            if r.stock_item_id in goods
            else "",
            "options": dict(r.options or {}),
            "options_text": _variant_text(menu.get(r.menu_item_id), dict(r.options or {})),
            "per_unit": float(r.per_unit),
        }
        for r in rows
    ]


@router.post("/recipes", status_code=201)
def add_recipe(
    body: RecipeIn,
    actor: User = Depends(require("stock.edit")),
    db: DbSession = Depends(get_db),
    venue: Venue = Depends(get_venue),
) -> dict:
    menu_item = db.get(MenuItem, body.menu_item_id)
    if menu_item is None or menu_item.venue_id != venue.id:
        raise HTTPException(status_code=404, detail="позиции меню нет")
    goods = _item(db, venue, body.stock_item_id)

    row = Recipe(
        venue_id=venue.id,
        menu_item_id=menu_item.id,
        stock_item_id=goods.id,
        options=body.options or {},
        per_unit=Decimal(str(body.per_unit)),
    )
    db.add(row)
    db.commit()
    return {"id": str(row.id), "menu_item": menu_item.name, "stock_item": goods.name}


@router.delete("/recipes/{recipe_id}")
def drop_recipe(
    recipe_id: uuid.UUID,
    actor: User = Depends(require("stock.edit")),
    db: DbSession = Depends(get_db),
    venue: Venue = Depends(get_venue),
) -> dict:
    row = db.get(Recipe, recipe_id)
    if row is None or row.venue_id != venue.id:
        raise HTTPException(status_code=404, detail="правила нет")
    db.delete(row)
    db.commit()
    return {"status": "ok"}
