"""Планшет бара и кухни: марки и две кнопки."""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.orm import Session as DbSession

from app.core.config import settings
from app.core.deps import current_user, get_venue, require
from app.db import get_db
from app.models import (
    ROLE_BAR,
    ROLE_KITCHEN,
    STATION_BAR,
    STATION_KITCHEN,
    STATION_NAMES,
    STATIONS,
    TICKET_READY,
    TICKET_SERVED,
    Check,
    Order,
    Table,
    Ticket,
    User,
    Venue,
    utcnow,
)
from app.services import push, realtime
from app.services.checks import CheckError, set_ticket_status, ticket_payload

router = APIRouter(prefix="/api/station", tags=["станция"])

# Роль сама говорит, за какой станцией человек стоит. Бармену не нужно
# выбирать «бар» каждую смену, и он не может случайно забрать марку кухни.
ROLE_STATION = {ROLE_BAR: STATION_BAR, ROLE_KITCHEN: STATION_KITCHEN}


def station_for(user: User, asked: str | None) -> str:
    fixed = ROLE_STATION.get(user.role)
    if fixed:
        return fixed
    if asked in STATIONS:
        return asked
    return STATION_BAR


def _context(db: DbSession, ticket: Ticket) -> tuple[Order, Check, str | None, str | None]:
    order = db.get(Order, ticket.order_id)
    check = db.get(Check, order.check_id)
    table = db.get(Table, check.table_id)
    waiter = db.get(User, check.waiter_id) if check.waiter_id else None
    return order, check, (table.label if table else None), (waiter.name if waiter else None)


@router.get("/queue")
def queue(
    station: str | None = Query(default=None, pattern="^(bar|kitchen)$"),
    actor: User = Depends(require("tickets.view")),
    db: DbSession = Depends(get_db),
    venue: Venue = Depends(get_venue),
) -> dict:
    """Очередь станции. Отданное не показывается — оно уже не работа."""
    which = station_for(actor, station)
    tickets = db.scalars(
        select(Ticket)
        .join(Order, Order.id == Ticket.order_id)
        .join(Check, Check.id == Order.check_id)
        .where(
            Check.venue_id == venue.id,
            Ticket.station == which,
            Ticket.status != TICKET_SERVED,
        )
        .order_by(Ticket.created_at)
    ).all()

    now = utcnow()
    rows = []
    for ticket in tickets:
        order, check, label, waiter = _context(db, ticket)
        payload = ticket_payload(ticket, order, check, label, waiter)
        waited = int((now - (order.sent_at or ticket.created_at)).total_seconds())
        payload["waited_seconds"] = waited
        # Просрочка — это не украшение: марка, которую не взяли две минуты,
        # должна выделяться, пока её не взяли.
        payload["late"] = ticket.status == "new" and waited >= settings.late_ticket_seconds
        rows.append(payload)

    return {
        "station": which,
        "station_name": STATION_NAMES.get(which, which),
        "tickets": rows,
    }


@router.post("/tickets/{ticket_id}/served")
def served(
    ticket_id: uuid.UUID,
    actor: User = Depends(require("checks.edit")),
    db: DbSession = Depends(get_db),
    venue: Venue = Depends(get_venue),
) -> dict:
    """«Забрал» жмёт официант, а не станция: это он унёс тарелку к столу.

    Тем же нажатием гасится повторяющийся сигнал.
    """
    ticket = db.get(Ticket, ticket_id)
    if ticket is None:
        raise HTTPException(status_code=404, detail="марка не найдена")
    order, check, label, waiter = _context(db, ticket)
    if check.venue_id != venue.id:
        raise HTTPException(status_code=404, detail="марка не найдена")

    try:
        set_ticket_status(db, ticket, TICKET_SERVED, actor)
    except CheckError as exc:
        raise HTTPException(status_code=exc.status, detail=exc.message) from None
    db.commit()

    realtime.publish(
        realtime.station_channel(ticket.station),
        {"type": "ticket.changed", "ticket_id": str(ticket.id)},
    )
    realtime.publish(realtime.CHANNEL_FLOOR, {"type": "check.changed", "check_id": str(check.id)})
    return ticket_payload(ticket, order, check, label, waiter)


# Объявлено ПОСЛЕ «забрал» намеренно: путь с переменной в конце перехватил бы
# и /served, и официант получал бы отказ на своей же кнопке.
@router.post("/tickets/{ticket_id}/{target}")
def move(
    ticket_id: uuid.UUID,
    target: str,
    actor: User = Depends(require("tickets.status")),
    db: DbSession = Depends(get_db),
    venue: Venue = Depends(get_venue),
) -> dict:
    """«Принял» и «Готово» двигают свою марку, а не весь заказ.

    Поэтому «готово» в баре не делает готовым то, что кухня ещё жарит.
    """
    if target not in ("accepted", "ready"):
        raise HTTPException(status_code=404, detail="неизвестное действие")

    ticket = db.get(Ticket, ticket_id)
    if ticket is None:
        raise HTTPException(status_code=404, detail="марка не найдена")
    order, check, label, waiter = _context(db, ticket)
    if check.venue_id != venue.id:
        raise HTTPException(status_code=404, detail="марка не найдена")
    if ticket.station != station_for(actor, None) and actor.role in ROLE_STATION:
        raise HTTPException(status_code=403, detail="это марка другой станции")

    try:
        set_ticket_status(db, ticket, target, actor)
    except CheckError as exc:
        raise HTTPException(status_code=exc.status, detail=exc.message) from None
    db.commit()

    realtime.publish(
        realtime.station_channel(ticket.station),
        {"type": "ticket.changed", "ticket_id": str(ticket.id)},
    )
    if ticket.status == TICKET_READY and check.waiter_id:
        # Ради этого события существует половина системы: бармен нажал
        # «Готово» — официант должен услышать это сейчас, а не когда
        # соберётся посмотреть в телефон.
        station_name = STATION_NAMES.get(ticket.station, ticket.station)
        realtime.publish(
            realtime.waiter_channel(check.waiter_id),
            {
                "type": "ticket.ready",
                "ticket_id": str(ticket.id),
                "check_id": str(check.id),
                "table": label,
                "station": ticket.station,
                "station_name": station_name,
            },
        )
        # Второй уровень — на случай свёрнутого приложения. Он не заменяет
        # звук в открытом приложении, а страхует его.
        push.notify(
            check.waiter_id,
            {
                "title": f"Готово · {station_name}",
                "body": f"Стол {label or '—'} · чек №{check.number}",
                "tag": f"ready-{ticket.id}",
                "url": "/",
            },
        )
    realtime.publish(realtime.CHANNEL_FLOOR, {"type": "check.changed", "check_id": str(check.id)})
    return ticket_payload(ticket, order, check, label, waiter)


@router.get("/waiting")
def waiting(
    actor: User = Depends(current_user),
    db: DbSession = Depends(get_db),
    venue: Venue = Depends(get_venue),
) -> list[dict]:
    """Готовые марки этого официанта, которые он ещё не забрал.

    Телефон опрашивает это при возврате на передний план: сокет мог
    оборваться, пока экран был погашен, и сигнал пропасть.
    """
    from app.services.checks import waiting_tickets

    out = []
    for ticket in waiting_tickets(db, venue, actor.id):
        order, check, label, waiter = _context(db, ticket)
        out.append(ticket_payload(ticket, order, check, label, waiter))
    return out
