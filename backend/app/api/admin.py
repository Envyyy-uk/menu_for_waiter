"""Админка: персонал, столы, меню, отчёт по смене, журнал.

Всё, что здесь меняется, меняется через сервер и пишется в журнал. Права
проверяются на каждом эндпойнте, а не тем, что кнопку не нарисовали.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.orm import Session as DbSession

from app.core.deps import get_venue, require
from app.core.permissions import can_assign_role
from app.db import get_db
from app.models import (
    CHECK_CLOSED,
    ITEM_CANCELLED,
    PAY_CARD,
    PAY_CASH,
    ROLE_NAMES,
    ROLES,
    STATION_NAMES,
    STATIONS,
    AuditLog,
    Check,
    CheckItem,
    MenuItem,
    Payment,
    Table,
    User,
    Venue,
    new_table_token,
    utcnow,
)
from app.services.audit import record
from app.services.auth import PIN_LENGTH, AuthError, issue_pin

router = APIRouter(prefix="/api/admin", tags=["админка"])


def _fail(exc: AuthError):
    raise HTTPException(status_code=exc.status, detail=exc.message)


# -------------------------------------------------------------- персонал ---
def user_payload(user: User) -> dict:
    return {
        "id": str(user.id),
        "name": user.name,
        "role": user.role,
        "role_name": ROLE_NAMES.get(user.role, user.role),
        "colour": user.colour,
        "active": user.active,
        "has_pin": bool(user.pin_hash),
    }


@router.get("/roles")
def roles(actor: User = Depends(require("users.manage"))) -> list[dict]:
    return [{"key": r, "name": ROLE_NAMES[r]} for r in ROLES]


@router.get("/users")
def users(
    actor: User = Depends(require("users.manage")),
    db: DbSession = Depends(get_db),
    venue: Venue = Depends(get_venue),
) -> list[dict]:
    rows = db.scalars(
        select(User).where(User.venue_id == venue.id).order_by(User.active.desc(), User.name)
    ).all()
    return [user_payload(u) for u in rows]


class UserIn(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    role: str
    colour: str = "#a25a2a"
    # Пустой PIN — сервер придумает свободный и покажет его один раз.
    pin: str | None = None


@router.post("/users", status_code=201)
def create_user(
    body: UserIn,
    actor: User = Depends(require("users.manage")),
    db: DbSession = Depends(get_db),
    venue: Venue = Depends(get_venue),
) -> dict:
    if not can_assign_role(actor.role, body.role):
        raise HTTPException(status_code=403, detail="нельзя выдать роль выше своей")

    user = User(venue_id=venue.id, name=body.name.strip(), role=body.role, colour=body.colour)
    db.add(user)
    db.flush()
    try:
        pin = issue_pin(db, user, body.pin)
    except AuthError as exc:
        db.rollback()
        _fail(exc)
    record.write(
        db,
        venue_id=venue.id,
        user_id=actor.id,
        action="user.create",
        entity=f"user:{user.id}",
        after={"name": user.name, "role": user.role},
    )
    db.commit()
    # PIN показывается один раз — дальше в базе только хеш, и подсмотреть его
    # нельзя даже администратору.
    return {**user_payload(user), "pin": pin}


class UserPatch(BaseModel):
    name: str | None = None
    role: str | None = None
    colour: str | None = None
    active: bool | None = None


@router.patch("/users/{user_id}")
def edit_user(
    user_id: uuid.UUID,
    body: UserPatch,
    actor: User = Depends(require("users.manage")),
    db: DbSession = Depends(get_db),
    venue: Venue = Depends(get_venue),
) -> dict:
    user = db.get(User, user_id)
    if user is None or user.venue_id != venue.id:
        raise HTTPException(status_code=404, detail="сотрудник не найден")
    if body.role is not None and not can_assign_role(actor.role, body.role):
        raise HTTPException(status_code=403, detail="нельзя выдать роль выше своей")
    if body.active is False and user.id == actor.id:
        # Иначе администратор выключает сам себя и остаётся снаружи.
        raise HTTPException(status_code=409, detail="нельзя отключить самого себя")

    before = user_payload(user)
    if body.name is not None:
        user.name = body.name.strip()
    if body.role is not None:
        user.role = body.role
    if body.colour is not None:
        user.colour = body.colour
    if body.active is not None:
        user.active = body.active
    record.write(
        db,
        venue_id=venue.id,
        user_id=actor.id,
        action="user.edit",
        entity=f"user:{user.id}",
        before=before,
        after=user_payload(user),
    )
    db.commit()
    return user_payload(user)


class PinIn(BaseModel):
    pin: str | None = None


@router.post("/users/{user_id}/pin")
def reset_pin(
    user_id: uuid.UUID,
    body: PinIn,
    actor: User = Depends(require("users.manage")),
    db: DbSession = Depends(get_db),
    venue: Venue = Depends(get_venue),
) -> dict:
    user = db.get(User, user_id)
    if user is None or user.venue_id != venue.id:
        raise HTTPException(status_code=404, detail="сотрудник не найден")
    try:
        pin = issue_pin(db, user, body.pin)
    except AuthError as exc:
        db.rollback()
        _fail(exc)
    record.write(
        db,
        venue_id=venue.id,
        user_id=actor.id,
        action="user.pin",
        entity=f"user:{user.id}",
        after={"name": user.name},
    )
    db.commit()
    return {**user_payload(user), "pin": pin, "pin_length": PIN_LENGTH}


# ----------------------------------------------------------------- столы ---
def table_payload(table: Table, open_checks: int = 0) -> dict:
    return {
        "id": str(table.id),
        "label": table.label,
        "zone": table.zone,
        "seats": table.seats,
        "position": table.position,
        "active": table.active,
        "open_checks": open_checks,
    }


@router.get("/tables")
def tables(
    actor: User = Depends(require("tables.manage")),
    db: DbSession = Depends(get_db),
    venue: Venue = Depends(get_venue),
) -> list[dict]:
    rows = db.scalars(
        select(Table).where(Table.venue_id == venue.id).order_by(Table.zone, Table.position)
    ).all()
    counts = dict(
        db.execute(
            select(Check.table_id, func.count())
            .where(Check.venue_id == venue.id, Check.status == "open")
            .group_by(Check.table_id)
        ).all()
    )
    return [table_payload(t, counts.get(t.id, 0)) for t in rows]


class TableIn(BaseModel):
    label: str = Field(min_length=1, max_length=40)
    zone: str = "Зал"
    seats: int = Field(default=4, ge=1, le=99)
    position: int = 0


@router.post("/tables", status_code=201)
def create_table(
    body: TableIn,
    actor: User = Depends(require("tables.manage")),
    db: DbSession = Depends(get_db),
    venue: Venue = Depends(get_venue),
) -> dict:
    exists = db.scalars(
        select(Table).where(Table.venue_id == venue.id, Table.label == body.label.strip())
    ).first()
    if exists is not None:
        raise HTTPException(status_code=409, detail="стол с таким номером уже есть")
    table = Table(
        venue_id=venue.id,
        label=body.label.strip(),
        zone=body.zone.strip() or "Зал",
        seats=body.seats,
        position=body.position,
        token=new_table_token(),
    )
    db.add(table)
    db.commit()
    return table_payload(table)


class TablePatch(BaseModel):
    label: str | None = None
    zone: str | None = None
    seats: int | None = Field(default=None, ge=1, le=99)
    position: int | None = None
    active: bool | None = None


@router.patch("/tables/{table_id}")
def edit_table(
    table_id: uuid.UUID,
    body: TablePatch,
    actor: User = Depends(require("tables.manage")),
    db: DbSession = Depends(get_db),
    venue: Venue = Depends(get_venue),
) -> dict:
    table = db.get(Table, table_id)
    if table is None or table.venue_id != venue.id:
        raise HTTPException(status_code=404, detail="стол не найден")

    if body.active is False:
        # Стол с открытым чеком выключать нельзя: чек повиснет в никуда, и
        # деньги за него никто не возьмёт.
        busy = db.scalars(
            select(Check).where(Check.table_id == table.id, Check.status == "open")
        ).first()
        if busy is not None:
            raise HTTPException(status_code=409, detail="на столе открыт чек")

    if body.label is not None:
        table.label = body.label.strip()
    if body.zone is not None:
        table.zone = body.zone.strip() or "Зал"
    if body.seats is not None:
        table.seats = body.seats
    if body.position is not None:
        table.position = body.position
    if body.active is not None:
        table.active = body.active
    db.commit()
    return table_payload(table)


# ------------------------------------------------------------------ меню ---
class MenuPatch(BaseModel):
    name: str | None = None
    description: str | None = None
    price_pence: int | None = Field(default=None, ge=0)
    station: str | None = None
    category: str | None = None
    active: bool | None = None


@router.patch("/menu/{item_id}")
def edit_item(
    item_id: uuid.UUID,
    body: MenuPatch,
    actor: User = Depends(require("items.edit")),
    db: DbSession = Depends(get_db),
    venue: Venue = Depends(get_venue),
) -> dict:
    item = db.get(MenuItem, item_id)
    if item is None or item.venue_id != venue.id:
        raise HTTPException(status_code=404, detail="позиция не найдена")
    if body.station is not None and body.station not in STATIONS:
        raise HTTPException(status_code=422, detail="неизвестная станция")

    before = {"name": item.name, "price_pence": item.price_pence, "station": item.station}
    if body.name is not None:
        item.name = body.name.strip()
    if body.description is not None:
        item.description = body.description.strip()
    if body.price_pence is not None:
        item.price_pence = body.price_pence
    if body.station is not None:
        item.station = body.station
    if body.category is not None:
        item.category = body.category
    if body.active is not None:
        item.active = body.active

    # Цена — это деньги, и кто её поменял, должно быть видно.
    record.write(
        db,
        venue_id=venue.id,
        user_id=actor.id,
        action="item.edit",
        entity=f"item:{item.key}",
        before=before,
        after={"name": item.name, "price_pence": item.price_pence, "station": item.station},
    )
    db.commit()
    from app.api.menu import item_payload
    from app.services import realtime

    realtime.publish(realtime.CHANNEL_ALL, {"type": "menu.state", "key": item.key})
    return item_payload(item)


# ---------------------------------------------------------------- отчёт ----
@router.get("/report")
def report(
    since: datetime | None = Query(default=None),
    until: datetime | None = Query(default=None),
    actor: User = Depends(require("reports")),
    db: DbSession = Depends(get_db),
    venue: Venue = Depends(get_venue),
) -> dict:
    """Отчёт по смене: сколько наличными, сколько картой, средний чек.

    По умолчанию — сутки назад. Смена в баре кончается за полночь, поэтому
    «сегодня» здесь означает последние 24 часа, а не календарный день.
    """
    until = until or utcnow()
    since = since or (until - timedelta(hours=24))

    closed = db.scalars(
        select(Check).where(
            Check.venue_id == venue.id,
            Check.status == CHECK_CLOSED,
            Check.closed_at >= since,
            Check.closed_at <= until,
        )
    ).all()

    payments = db.execute(
        select(Payment.method, func.sum(Payment.amount_pence), func.count())
        .join(Check, Check.id == Payment.check_id)
        .where(
            Check.venue_id == venue.id,
            Check.status == CHECK_CLOSED,
            Check.closed_at >= since,
            Check.closed_at <= until,
        )
        .group_by(Payment.method)
    ).all()
    by_method = {method: {"amount_pence": int(total), "count": count} for method, total, count in payments}

    revenue = sum(v["amount_pence"] for v in by_method.values())
    names = {u.id: u.name for u in db.scalars(select(User).where(User.venue_id == venue.id)).all()}

    by_waiter: dict[str, dict] = {}
    for check in closed:
        key = names.get(check.waiter_id, "—")
        row = by_waiter.setdefault(key, {"checks": 0, "amount_pence": 0, "guests": 0})
        row["checks"] += 1
        row["guests"] += check.guests
        row["amount_pence"] += sum(
            i.unit_price_pence * i.qty for i in check.items if i.status != ITEM_CANCELLED
        ) - (check.discount_pence or 0)

    # Отмены после отправки — то, ради чего отчёт вообще открывают, когда
    # сходится не всё.
    cancelled = db.execute(
        select(func.count(), func.coalesce(func.sum(CheckItem.unit_price_pence * CheckItem.qty), 0))
        .join(Check, Check.id == CheckItem.check_id)
        .where(
            Check.venue_id == venue.id,
            CheckItem.status == ITEM_CANCELLED,
            CheckItem.cancelled_at >= since,
            CheckItem.cancelled_at <= until,
        )
    ).one()

    top = db.execute(
        select(CheckItem.name_snapshot, func.sum(CheckItem.qty))
        .join(Check, Check.id == CheckItem.check_id)
        .where(
            Check.venue_id == venue.id,
            Check.status == CHECK_CLOSED,
            Check.closed_at >= since,
            Check.closed_at <= until,
            CheckItem.status != ITEM_CANCELLED,
        )
        .group_by(CheckItem.name_snapshot)
        .order_by(func.sum(CheckItem.qty).desc())
        .limit(10)
    ).all()

    return {
        "since": since.isoformat(),
        "until": until.isoformat(),
        "checks": len(closed),
        "guests": sum(c.guests for c in closed),
        "revenue_pence": revenue,
        "average_pence": revenue // len(closed) if closed else 0,
        "cash_pence": by_method.get(PAY_CASH, {}).get("amount_pence", 0),
        "card_pence": by_method.get(PAY_CARD, {}).get("amount_pence", 0),
        "discount_pence": sum(c.discount_pence or 0 for c in closed),
        "cancelled": {"count": cancelled[0], "amount_pence": int(cancelled[1])},
        "by_waiter": [
            {"name": name, **row} for name, row in sorted(by_waiter.items(), key=lambda kv: -kv[1]["amount_pence"])
        ],
        "top_items": [{"name": name, "qty": int(qty)} for name, qty in top],
        "stations": [{"key": s, "name": STATION_NAMES[s]} for s in STATIONS],
    }


@router.get("/audit")
def audit(
    limit: int = Query(default=100, ge=1, le=500),
    actor: User = Depends(require("audit.view")),
    db: DbSession = Depends(get_db),
    venue: Venue = Depends(get_venue),
) -> list[dict]:
    rows = db.scalars(
        select(AuditLog)
        .where(AuditLog.venue_id == venue.id)
        .order_by(AuditLog.at.desc())
        .limit(limit)
    ).all()
    names = {u.id: u.name for u in db.scalars(select(User).where(User.venue_id == venue.id)).all()}
    return [
        {
            "at": r.at.isoformat(),
            "who": names.get(r.user_id, "—"),
            "action": r.action,
            "entity": r.entity,
            "before": r.before,
            "after": r.after,
        }
        for r in rows
    ]
