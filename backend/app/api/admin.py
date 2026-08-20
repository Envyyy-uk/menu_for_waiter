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
from app.core.permissions import can_assign_role, can_touch_user
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
from app.services import menu_sync
from app.services.audit import record
from app.services.auth import AuthError, issue_pin, pin_length

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
def roles(actor: User = Depends(require("users.view"))) -> list[dict]:
    return [{"key": r, "name": ROLE_NAMES[r]} for r in ROLES]


@router.get("/users")
def users(
    actor: User = Depends(require("users.view")),
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
    return {**user_payload(user), "pin": pin, "pin_length": pin_length(user.role)}


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
    if not can_touch_user(actor.role, user.role):
        raise HTTPException(status_code=403, detail="нельзя трогать роль выше своей")
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

    # Роль переехала через границу «зал ↔ админка» — старый PIN стал не той
    # длины, и войти по нему больше нельзя. Молча оставить его значит запереть
    # человека снаружи, поэтому здесь же выдаётся новый: администратор видит
    # его один раз и передаёт из рук в руки.
    fresh = None
    if body.role is not None and pin_length(user.role) != pin_length(before["role"]):
        if user.pin_hash is not None:
            try:
                fresh = issue_pin(db, user)
            except AuthError as exc:
                db.rollback()
                _fail(exc)

    record.write(
        db,
        venue_id=venue.id,
        user_id=actor.id,
        action="user.edit",
        entity=f"user:{user.id}",
        before=before,
        after=user_payload(user),
    )
    if fresh is not None:
        record.write(
            db,
            venue_id=venue.id,
            user_id=actor.id,
            action="user.pin",
            entity=f"user:{user.id}",
            after={"name": user.name, "reason": "смена роли"},
        )
    db.commit()
    out = user_payload(user)
    if fresh is not None:
        out |= {"pin": fresh, "pin_length": pin_length(user.role)}
    return out


class PinIn(BaseModel):
    pin: str | None = None


@router.post("/users/{user_id}/pin")
def reset_pin(
    user_id: uuid.UUID,
    body: PinIn,
    actor: User = Depends(require("users.pin")),
    db: DbSession = Depends(get_db),
    venue: Venue = Depends(get_venue),
) -> dict:
    """Сброс чужого PIN — по просьбе или когда забыли.

    Умеет и менеджер: официант, оставшийся без входа посреди смены, не должен
    ждать администратора. Но выше себя не трогает никто — иначе менеджер
    сбрасывает PIN владельцу и заходит вместо него.
    """
    user = db.get(User, user_id)
    if user is None or user.venue_id != venue.id:
        raise HTTPException(status_code=404, detail="сотрудник не найден")
    if not can_touch_user(actor.role, user.role):
        raise HTTPException(status_code=403, detail="нельзя трогать роль выше своей")
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
    return {**user_payload(user), "pin": pin, "pin_length": pin_length(user.role)}


# ----------------------------------------------------------------- столы ---
def table_payload(table: Table, open_checks: int = 0, ever_used: bool = False) -> dict:
    return {
        "id": str(table.id),
        "label": table.label,
        "zone": table.zone,
        "seats": table.seats,
        "position": table.position,
        "x": table.x,
        "y": table.y,
        "active": table.active,
        "open_checks": open_checks,
        # Стол, по которому были чеки, удалить нельзя — на него ссылается
        # история. Кнопку прячем заранее, чтобы не предлагать невозможное.
        "ever_used": ever_used,
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
    used = {
        row[0]
        for row in db.execute(
            select(Check.table_id).where(Check.venue_id == venue.id).distinct()
        ).all()
    }
    return [table_payload(t, counts.get(t.id, 0), t.id in used) for t in rows]


class TableIn(BaseModel):
    label: str = Field(min_length=1, max_length=40)
    zone: str = "Зал"
    seats: int = Field(default=4, ge=1, le=99)
    position: int = 0
    # Место на плане в процентах от зала: план рисуют на ноутбуке, а смотрят
    # на телефоне.
    x: float | None = Field(default=None, ge=0, le=100)
    y: float | None = Field(default=None, ge=0, le=100)


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
        x=body.x,
        y=body.y,
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
    x: float | None = Field(default=None, ge=0, le=100)
    y: float | None = Field(default=None, ge=0, le=100)


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
        label = body.label.strip()
        if label != table.label:
            twin = db.scalars(
                select(Table).where(
                    Table.venue_id == venue.id, Table.label == label, Table.id != table.id
                )
            ).first()
            if twin is not None:
                raise HTTPException(status_code=409, detail="стол с таким номером уже есть")
        table.label = label
    if body.zone is not None:
        table.zone = body.zone.strip() or "Зал"
    if body.seats is not None:
        table.seats = body.seats
    if body.position is not None:
        table.position = body.position
    if body.active is not None:
        table.active = body.active
    if body.x is not None:
        table.x = body.x
    if body.y is not None:
        table.y = body.y
    db.commit()
    _plan_changed()
    return table_payload(table)


class Spot(BaseModel):
    id: uuid.UUID
    x: float = Field(ge=0, le=100)
    y: float = Field(ge=0, le=100)
    zone: str | None = None


class PlanIn(BaseModel):
    tables: list[Spot]


@router.post("/tables/plan")
def save_plan(
    body: PlanIn,
    actor: User = Depends(require("tables.manage")),
    db: DbSession = Depends(get_db),
    venue: Venue = Depends(get_venue),
) -> list[dict]:
    """Сохранить расстановку целиком, одним запросом.

    Именно целиком: пока стол тащат пальцем, он меняет место сто раз, и сто
    запросов по дороге — это сто шансов оставить план наполовину сохранённым.
    """
    known = {
        t.id: t for t in db.scalars(select(Table).where(Table.venue_id == venue.id)).all()
    }
    for spot in body.tables:
        table = known.get(spot.id)
        if table is None:
            continue
        table.x = spot.x
        table.y = spot.y
        if spot.zone:
            table.zone = spot.zone.strip() or table.zone
    db.commit()
    _plan_changed()
    return [table_payload(t) for t in known.values()]


@router.delete("/tables/{table_id}")
def remove_table(
    table_id: uuid.UUID,
    actor: User = Depends(require("tables.manage")),
    db: DbSession = Depends(get_db),
    venue: Venue = Depends(get_venue),
) -> dict:
    """Убрать стол насовсем — только если по нему никогда не было чеков.

    Иначе история потеряет стол, на который ссылается: закрытый чек должен
    знать, где сидели. Такой стол выключают, а не удаляют.
    """
    table = db.get(Table, table_id)
    if table is None or table.venue_id != venue.id:
        raise HTTPException(status_code=404, detail="стол не найден")
    used = db.scalars(select(Check).where(Check.table_id == table.id)).first()
    if used is not None:
        raise HTTPException(
            status_code=409,
            detail="по столу были чеки — его можно выключить, но не удалить",
        )
    db.delete(table)
    db.commit()
    _plan_changed()
    return {"status": "ok"}


def _plan_changed() -> None:
    """Официанты видят новую расстановку сразу — план меняют перед сменой,
    и бегать перезапускать телефоны в этот момент некому."""
    from app.services import realtime

    realtime.publish(realtime.CHANNEL_ALL, {"type": "tables.changed"})


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


# ------------------------------------------------------- станции ---------
class StationPinIn(BaseModel):
    station: str
    pin: str = Field(min_length=4, max_length=4)


@router.get("/stations")
def stations(
    actor: User = Depends(require("stations.manage")),
    db: DbSession = Depends(get_db),
    venue: Venue = Depends(get_venue),
) -> list[dict]:
    """PIN планшета и текущая смена по каждой станции."""
    from app.models import STATION_NAMES, STATIONS
    from app.services import shifts

    out = []
    for station in STATIONS:
        live = shifts.current(db, venue.id, station)
        out.append(
            {
                "station": station,
                "name": STATION_NAMES[station],
                "has_pin": shifts.has_pin(db, venue.id, station),
                "shift": shifts.payload(live, station),
            }
        )
    return out


@router.post("/stations/pin")
def station_pin(
    body: StationPinIn,
    actor: User = Depends(require("stations.manage")),
    db: DbSession = Depends(get_db),
    venue: Venue = Depends(get_venue),
) -> dict:
    """Задать или сменить PIN планшета станции.

    Он отдельный от личных намеренно: планшет стоит на полке, к нему подходят
    все по очереди, и личный PIN на каждую марку никто вводить не станет.
    """
    from app.services import shifts

    try:
        shifts.set_pin(db, venue.id, body.station, body.pin, actor)
    except AuthError as exc:
        db.rollback()
        raise HTTPException(status_code=exc.status, detail=exc.message) from None
    db.commit()
    return {"status": "ok", "station": body.station}


@router.get("/shifts")
def shift_log(
    limit: int = Query(default=30, ge=1, le=200),
    actor: User = Depends(require("shifts.view")),
    db: DbSession = Depends(get_db),
    venue: Venue = Depends(get_venue),
) -> list[dict]:
    from app.models import STATION_NAMES, Shift

    rows = db.scalars(
        select(Shift)
        .where(Shift.venue_id == venue.id)
        .order_by(Shift.opened_at.desc())
        .limit(limit)
    ).all()
    return [
        {
            "station": s.station,
            "name": STATION_NAMES.get(s.station, s.station),
            "opened_at": s.opened_at.isoformat(),
            "closed_at": s.closed_at.isoformat() if s.closed_at else None,
            "tickets_done": s.tickets_done,
            "note": s.note,
        }
        for s in rows
    ]


# ------------------------------------------------------ меню с сайта -----
@router.get("/menu/sync")
def sync_status(
    actor: User = Depends(require("items.edit")),
    venue: Venue = Depends(get_venue),
) -> dict:
    return menu_sync.status(venue)


@router.post("/menu/sync")
def sync_now(
    actor: User = Depends(require("items.edit")),
    db: DbSession = Depends(get_db),
    venue: Venue = Depends(get_venue),
) -> dict:
    """Сходить за меню прямо сейчас.

    Обычно это делается само раз в несколько минут, но перед сменой удобно не
    ждать: поправили цену на сайте — нажали здесь и увидели.

    `force` намеренный: кнопку жмут именно тогда, когда не верят, что метка
    версии на сайте поменялась.
    """
    result = menu_sync.sync_once(db, venue, force=True, actor_id=actor.id)
    return {**result, "state": menu_sync.status(venue)}


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


@router.get("/payments")
def payments(
    hours: int = Query(default=24, ge=1, le=24 * 31),
    limit: int = Query(default=200, ge=1, le=1000),
    actor: User = Depends(require("payments.view")),
    db: DbSession = Depends(get_db),
    venue: Venue = Depends(get_venue),
) -> dict:
    """Закрытые чеки: чем платили, сколько и что было внутри.

    Отчёт отвечает «сколько всего», а это — «за что именно». Когда касса не
    сходится или гость возвращается со словами «мне посчитали лишнее», нужен
    именно такой список: позиции, скидка с причиной и способ оплаты рядом.
    """
    until = utcnow()
    since = until - timedelta(hours=hours)

    closed = db.scalars(
        select(Check)
        .where(
            Check.venue_id == venue.id,
            Check.status == CHECK_CLOSED,
            Check.closed_at >= since,
        )
        .order_by(Check.closed_at.desc())
        .limit(limit)
    ).all()

    names = {u.id: u.name for u in db.scalars(select(User).where(User.venue_id == venue.id)).all()}
    labels = {t.id: t.label for t in db.scalars(select(Table).where(Table.venue_id == venue.id)).all()}

    rows = []
    for check in closed:
        live = [i for i in check.items if i.status != ITEM_CANCELLED]
        rows.append(
            {
                "id": str(check.id),
                "number": check.number,
                "table": labels.get(check.table_id, "—"),
                "guests": check.guests,
                "waiter": names.get(check.waiter_id, "—"),
                "closed_by": names.get(check.closed_by_id, "—"),
                "closed_at": check.closed_at.isoformat() if check.closed_at else None,
                "subtotal_pence": sum(i.unit_price_pence * i.qty for i in live),
                "discount_pence": check.discount_pence or 0,
                "discount_reason": check.discount_reason,
                "total_pence": sum(p.amount_pence for p in check.payments),
                "payments": [
                    {
                        "method": p.method,
                        "amount_pence": p.amount_pence,
                        "tendered_pence": p.tendered_pence,
                    }
                    for p in sorted(check.payments, key=lambda p: p.created_at)
                ],
                "items": [
                    {
                        "name": i.name_snapshot,
                        "qty": i.qty,
                        "options": list(i.options_snapshot or []),
                        "total_pence": i.unit_price_pence * i.qty,
                    }
                    for i in sorted(live, key=lambda i: i.created_at)
                ],
                # Отменённое до оплаты — то, ради чего этот список и открывают,
                # когда сумма не та, которую гость помнит.
                "cancelled": [
                    {"name": i.name_snapshot, "qty": i.qty, "reason": i.cancel_reason}
                    for i in check.items
                    if i.status == ITEM_CANCELLED
                ],
            }
        )

    return {
        "since": since.isoformat(),
        "hours": hours,
        "checks": len(rows),
        "cash_pence": sum(
            p["amount_pence"] for r in rows for p in r["payments"] if p["method"] == PAY_CASH
        ),
        "card_pence": sum(
            p["amount_pence"] for r in rows for p in r["payments"] if p["method"] == PAY_CARD
        ),
        "discount_pence": sum(r["discount_pence"] for r in rows),
        "rows": rows,
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
