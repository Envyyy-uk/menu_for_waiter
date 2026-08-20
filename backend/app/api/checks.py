"""Открытые чеки: открыть стол, набрать, отправить, закрыть."""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session as DbSession

from app.core.deps import current_user, get_venue, require
from app.db import get_db
from app.models import (
    CHECK_OPEN,
    STATION_NAMES,
    Check,
    MenuItem,
    Table,
    User,
    Venue,
)
from app.services import realtime, stock
from app.services.audit import record
from app.services.checks import (
    CheckError,
    add_item,
    cancel_item,
    change_draft,
    check_payload,
    close_check,
    get_check,
    get_item,
    open_check,
    require_open,
    send,
    subtotal,
    total,
)

router = APIRouter(prefix="/api/checks", tags=["чеки"])


def _fail(exc: CheckError):
    raise HTTPException(status_code=exc.status, detail={"message": exc.message, **exc.payload})


def _names(db: DbSession, check: Check) -> tuple[str | None, str | None]:
    table = db.get(Table, check.table_id)
    waiter = db.get(User, check.waiter_id) if check.waiter_id else None
    return (table.label if table else None), (waiter.name if waiter else None)


def _answer(db: DbSession, check: Check) -> dict:
    db.refresh(check)
    label, waiter = _names(db, check)
    return check_payload(check, label, waiter)


def _touch(check: Check) -> None:
    """Сигнал «чек изменился» — его слушает и зал, и админка."""
    realtime.publish(
        realtime.CHANNEL_FLOOR, {"type": "check.changed", "check_id": str(check.id)}
    )


# ------------------------------------------------------------ открыть ----
class OpenIn(BaseModel):
    table_id: uuid.UUID
    guests: int = Field(default=1, ge=1, le=99)
    comment: str | None = None


@router.post("", status_code=201)
def create(
    body: OpenIn,
    actor: User = Depends(require("checks.edit")),
    db: DbSession = Depends(get_db),
    venue: Venue = Depends(get_venue),
) -> dict:
    table = db.get(Table, body.table_id)
    if table is None or table.venue_id != venue.id:
        raise HTTPException(status_code=404, detail="стол не найден")
    try:
        check = open_check(db, venue, table, actor, body.guests, body.comment)
    except CheckError as exc:
        _fail(exc)
    db.commit()
    _touch(check)
    return _answer(db, check)


@router.get("")
def listing(
    status: str = Query(default=CHECK_OPEN, pattern="^(open|closed)$"),
    mine: bool = Query(default=False),
    actor: User = Depends(require("checks.view")),
    db: DbSession = Depends(get_db),
    venue: Venue = Depends(get_venue),
) -> list[dict]:
    query = select(Check).where(Check.venue_id == venue.id, Check.status == status)
    if mine:
        query = query.where(Check.waiter_id == actor.id)
    checks = db.scalars(query.order_by(Check.created_at.desc())).all()
    return [check_payload(c, *_names(db, c)) for c in checks]


@router.get("/{check_id}")
def one(
    check_id: uuid.UUID,
    actor: User = Depends(require("checks.view")),
    db: DbSession = Depends(get_db),
    venue: Venue = Depends(get_venue),
) -> dict:
    try:
        check = get_check(db, venue, check_id)
    except CheckError as exc:
        _fail(exc)
    return _answer(db, check)


class CheckPatch(BaseModel):
    guests: int | None = Field(default=None, ge=1, le=99)
    comment: str | None = None


@router.patch("/{check_id}")
def patch(
    check_id: uuid.UUID,
    body: CheckPatch,
    actor: User = Depends(require("checks.edit")),
    db: DbSession = Depends(get_db),
    venue: Venue = Depends(get_venue),
) -> dict:
    try:
        check = require_open(get_check(db, venue, check_id))
    except CheckError as exc:
        _fail(exc)
    if body.guests is not None:
        check.guests = body.guests
    if body.comment is not None:
        check.comment = body.comment.strip() or None
    db.commit()
    _touch(check)
    return _answer(db, check)


# ------------------------------------------------------------- позиции ---
class ItemIn(BaseModel):
    menu_item_id: uuid.UUID
    qty: int = Field(default=1, ge=1, le=99)
    # {"size": "ml50", "mixer": ["mixer", "mixer"]} — цену считает сервер.
    options: dict | None = None
    note: str | None = None


@router.post("/{check_id}/items", status_code=201)
def add(
    check_id: uuid.UUID,
    body: ItemIn,
    actor: User = Depends(require("checks.edit")),
    db: DbSession = Depends(get_db),
    venue: Venue = Depends(get_venue),
) -> dict:
    try:
        check = require_open(get_check(db, venue, check_id))
        item = db.get(MenuItem, body.menu_item_id)
        if item is None or item.venue_id != venue.id:
            raise HTTPException(status_code=404, detail="позиция меню не найдена")
        add_item(
            db, check, item, qty=body.qty, options=body.options, note=body.note, user=actor
        )
        db.commit()
    except CheckError as exc:
        _fail(exc)
    return _answer(db, check)


class ItemPatch(BaseModel):
    qty: int | None = Field(default=None, ge=0, le=99)
    note: str | None = None


@router.patch("/{check_id}/items/{item_id}")
def edit(
    check_id: uuid.UUID,
    item_id: uuid.UUID,
    body: ItemPatch,
    actor: User = Depends(require("checks.edit")),
    db: DbSession = Depends(get_db),
    venue: Venue = Depends(get_venue),
) -> dict:
    try:
        check = get_check(db, venue, check_id)
        change_draft(db, check, get_item(db, check, item_id), qty=body.qty, note=body.note)
        db.commit()
    except CheckError as exc:
        _fail(exc)
    return _answer(db, check)


class CancelIn(BaseModel):
    reason: str | None = None


@router.post("/{check_id}/items/{item_id}/cancel")
def cancel(
    check_id: uuid.UUID,
    item_id: uuid.UUID,
    body: CancelIn,
    actor: User = Depends(current_user),
    db: DbSession = Depends(get_db),
    venue: Venue = Depends(get_venue),
) -> dict:
    """Черновик убирает официант сам. Отправленное — только менеджер и с
    причиной: иначе чек не документ, а черновик, где всё переписывается
    задним числом."""
    from app.core.permissions import can

    try:
        check = get_check(db, venue, check_id)
        row = get_item(db, check, item_id)
        if row.status != "draft" and not can(actor.role, "checks.void"):
            raise HTTPException(status_code=403, detail="отменить отправленное может менеджер")
        was_sent = row.status == "sent"
        station = row.station_snapshot
        name = row.name_snapshot
        cancel_item(db, check, row, user=actor, reason=body.reason)
        if was_sent:
            # Отменили отправленное — продукт вернулся на полку.
            stock.give_back(db, row, actor)
            record.write(
                db,
                venue_id=venue.id,
                user_id=actor.id,
                action="item.cancel",
                entity=f"check:{check.number}",
                after={"name": name, "reason": body.reason},
            )
        db.commit()
        if was_sent:
            # Бармен уже мог начать делать — об отмене он должен узнать,
            # а не догадаться по пустому столу.
            realtime.publish(
                realtime.station_channel(station),
                {"type": "ticket.changed", "check_id": str(check.id)},
            )
    except CheckError as exc:
        _fail(exc)
    _touch(check)
    return _answer(db, check)


# -------------------------------------------------------------- отправка --
@router.post("/{check_id}/send")
def send_order(
    check_id: uuid.UUID,
    actor: User = Depends(require("checks.edit")),
    db: DbSession = Depends(get_db),
    venue: Venue = Depends(get_venue),
) -> dict:
    try:
        check = get_check(db, venue, check_id)
        drafts = [i for i in check.items if i.status == "draft"]
        order, tickets = send(db, check, actor)
        # Позиция ушла на станцию — её уже наливают. Ждать закрытия чека
        # значит весь вечер видеть на складе остаток, которого там нет.
        for row in drafts:
            stock.consume(db, row, actor)
        db.commit()
    except CheckError as exc:
        _fail(exc)

    label, _ = _names(db, check)
    for ticket in tickets:
        # Планшет станции просыпается сразу: пока сигнал не дошёл, заказ
        # существует только в телефоне официанта.
        realtime.publish(
            realtime.station_channel(ticket.station),
            {
                "type": "ticket.new",
                "ticket_id": str(ticket.id),
                "table": label,
                "station": ticket.station,
                "station_name": STATION_NAMES.get(ticket.station, ticket.station),
            },
        )
    _touch(check)
    return _answer(db, check)


# --------------------------------------------------------------- скидка ---
class DiscountIn(BaseModel):
    discount_pence: int = Field(ge=0)
    reason: str | None = None


@router.post("/{check_id}/discount")
def discount(
    check_id: uuid.UUID,
    body: DiscountIn,
    actor: User = Depends(require("checks.discount")),
    db: DbSession = Depends(get_db),
    venue: Venue = Depends(get_venue),
) -> dict:
    try:
        check = require_open(get_check(db, venue, check_id))
    except CheckError as exc:
        _fail(exc)
    if body.discount_pence > subtotal(check):
        raise HTTPException(status_code=422, detail="скидка больше суммы чека")
    before = check.discount_pence
    check.discount_pence = body.discount_pence
    # Скидка без причины — это просто минус в кассе. Причина хранится на чеке
    # и видна в списке оплат рядом с суммой.
    check.discount_reason = (body.reason or "").strip() or None
    record.write(
        db,
        venue_id=venue.id,
        user_id=actor.id,
        action="check.discount",
        entity=f"check:{check.number}",
        before={"discount_pence": before},
        after={"discount_pence": check.discount_pence, "reason": body.reason},
    )
    db.commit()
    _touch(check)
    return _answer(db, check)


# --------------------------------------------------------------- оплата ---
class PartIn(BaseModel):
    method: str = Field(pattern="^(card|cash)$")
    amount_pence: int = Field(ge=1)
    # Сколько дали наличными: сдачу считает касса, а не официант в уме.
    tendered_pence: int | None = Field(default=None, ge=0)


class CloseIn(BaseModel):
    payments: list[PartIn]


@router.post("/{check_id}/close")
def close(
    check_id: uuid.UUID,
    body: CloseIn,
    actor: User = Depends(require("checks.close")),
    db: DbSession = Depends(get_db),
    venue: Venue = Depends(get_venue),
) -> dict:
    try:
        check = get_check(db, venue, check_id)
        close_check(db, check, [p.model_dump() for p in body.payments], actor)
        record.write(
            db,
            venue_id=venue.id,
            user_id=actor.id,
            action="check.close",
            entity=f"check:{check.number}",
            after={
                "total_pence": total(check),
                "payments": [
                    {"method": p.method, "amount_pence": p.amount_pence} for p in body.payments
                ],
            },
        )
        db.commit()
    except CheckError as exc:
        _fail(exc)
    _touch(check)
    return _answer(db, check)
