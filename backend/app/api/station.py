"""Планшет бара и кухни: марки и две кнопки."""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session as DbSession

from app.core.config import settings
from app.core.deps import StationAccess, current_user, get_venue, require, station_access
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
from app.services import push, realtime, shifts
from app.services.audit import record
from app.services.checks import CheckError, set_ticket_status, ticket_payload
from app.services.auth import AuthError
from app.services.shifts import SHIFT_COOKIE

router = APIRouter(prefix="/api/station", tags=["станция"])

# Роль сама говорит, за какой станцией человек стоит. Бармену не нужно
# выбирать «бар» каждую смену, и он не может случайно забрать марку кухни.
ROLE_STATION = {ROLE_BAR: STATION_BAR, ROLE_KITCHEN: STATION_KITCHEN}


def station_for(user: User | None, asked: str | None) -> str:
    """Какую станцию показывать. Роль отвечает раньше вопроса.

    Бармену не нужно выбирать «бар» каждую смену, и он не может случайно
    забрать марку кухни.
    """
    fixed = ROLE_STATION.get(user.role) if user else None
    if fixed:
        return fixed
    if asked in STATIONS:
        return asked
    return STATION_BAR


def station_of(access: StationAccess, asked: str | None) -> str:
    """Станция планшета известна из смены, человека — из роли."""
    if access.station:
        return access.station
    return station_for(access.user, asked)


def _context(db: DbSession, ticket: Ticket) -> tuple[Order, Check, str | None, str | None]:
    order = db.get(Order, ticket.order_id)
    check = db.get(Check, order.check_id)
    table = db.get(Table, check.table_id)
    waiter = db.get(User, check.waiter_id) if check.waiter_id else None
    return order, check, (table.label if table else None), (waiter.name if waiter else None)


@router.get("/queue")
def queue(
    station: str | None = Query(default=None, pattern="^(bar|kitchen)$"),
    access: StationAccess = Depends(station_access),
    db: DbSession = Depends(get_db),
    venue: Venue = Depends(get_venue),
) -> dict:
    """Очередь станции. Отданное не показывается — оно уже не работа."""
    which = station_of(access, station)
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
        # Планшету нужно знать, чья это смена и когда её открыли; человеку с
        # личным входом — нет, он и так знает, кто он.
        "shift": shifts.payload(access.shift, which) if access.shift else None,
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
    access: StationAccess = Depends(station_access),
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
    if access.station and ticket.station != access.station:
        raise HTTPException(status_code=403, detail="это марка другой станции")
    if access.user and access.user.role in ROLE_STATION and ticket.station != station_for(access.user, None):
        raise HTTPException(status_code=403, detail="это марка другой станции")

    try:
        set_ticket_status(db, ticket, target, access.user)
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


# ------------------------------------------------------------- смена -----
class ShiftPinIn(BaseModel):
    pin: str = Field(min_length=4, max_length=4)


class ShiftCloseIn(BaseModel):
    pin: str = Field(min_length=4, max_length=4)
    note: str | None = None


def _shift_cookie(answer: Response, token: str, days: int = 2) -> None:
    answer.set_cookie(
        SHIFT_COOKIE,
        token,
        max_age=days * 86400,
        httponly=True,
        samesite="lax",
        secure=settings.public_base_url.startswith("https://"),
        path="/",
    )


@router.get("/shift")
def shift_state(
    request: Request,
    db: DbSession = Depends(get_db),
    venue: Venue = Depends(get_venue),
) -> dict:
    """Что показывать планшету: очередь или экран PIN."""
    shift = shifts.by_token(db, request.cookies.get(SHIFT_COOKIE))
    if shift is None:
        return {
            "open": False,
            # Пока PIN станции не задан, планшет говорит об этом прямо, а не
            # отвергает любые четыре цифры молча.
            "configured": any(shifts.has_pin(db, venue.id, s) for s in STATIONS),
        }
    return {**shifts.payload(shift), "configured": True}


@router.post("/shift/open")
def shift_open(
    body: ShiftPinIn,
    db: DbSession = Depends(get_db),
    venue: Venue = Depends(get_venue),
) -> Response:
    """Открыть смену планшета.

    Станцию не спрашиваем: планшет бара и планшет кухни отличаются как раз
    PIN-ом, и лишний экран выбора — это лишний способ открыть чужую смену.
    """
    station = shifts.station_for_pin(db, venue.id, body.pin)
    if station is None:
        return JSONResponse(status_code=401, content={"detail": "Неверный PIN станции"})

    shift, token = shifts.open_shift(db, venue.id, station)
    db.commit()
    answer = JSONResponse({**shifts.payload(shift), "configured": True})
    _shift_cookie(answer, token)
    return answer


@router.post("/shift/close")
def shift_close(
    body: ShiftCloseIn,
    request: Request,
    db: DbSession = Depends(get_db),
    venue: Venue = Depends(get_venue),
) -> Response:
    """Закрыть смену — тем же PIN станции.

    Спрашивается он не для формальности: иначе смену закрывает любой, кто
    прошёл мимо планшета, и отчёт по станции превращается в набор огрызков.
    """
    shift = shifts.by_token(db, request.cookies.get(SHIFT_COOKIE))
    if shift is None:
        raise HTTPException(status_code=409, detail="смена не открыта")
    station = shifts.station_for_pin(db, venue.id, body.pin)
    if station != shift.station:
        return JSONResponse(status_code=401, content={"detail": "Неверный PIN станции"})

    shifts.close_shift(db, shift, body.note)
    db.commit()
    answer = JSONResponse({**shifts.payload(shift), "configured": True})
    answer.delete_cookie(SHIFT_COOKIE, path="/")
    return answer


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
