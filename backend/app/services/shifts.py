"""Смена планшета станции.

Планшет живёт отдельно от личных входов. Он стоит на полке весь вечер, к нему
подходят все по очереди, и требовать личный PIN на каждую марку — значит не
получить ни одного нажатия. Личная ответственность здесь и не нужна: планшет
показывает марки и двигает их статус, к деньгам он не прикасается.

Именное здесь одно — открытие и закрытие смены. Кто ввёл PIN, тот и открыл, и
это записано в журнале вместе с тем, сколько марок прошло.
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import func, select
from sqlalchemy.orm import Session as DbSession

from app.core.security import hash_secret, new_token, token_fingerprint, verify_secret
from app.models import (
    STATIONS,
    Check,
    Order,
    Shift,
    StationPin,
    Ticket,
    User,
    utcnow,
)
from app.services.audit import record
from app.services.auth import PIN_LENGTH, AuthError

SHIFT_COOKIE = "shift"

# Смена без закрытия не висит вечно: планшет забыли выключить — она закроется
# сама, и в отчёте это будет видно как «закрыта автоматически».
MAX_SHIFT_HOURS = 24


def set_pin(db: DbSession, venue_id, station: str, pin: str, actor: User) -> None:
    if station not in STATIONS:
        raise AuthError("неизвестная станция", status=422)
    pin = (pin or "").strip()
    if not pin.isdigit() or len(pin) != PIN_LENGTH:
        raise AuthError(f"PIN — ровно {PIN_LENGTH} цифры", status=422)

    row = db.scalars(
        select(StationPin).where(StationPin.venue_id == venue_id, StationPin.station == station)
    ).first()
    if row is None:
        row = StationPin(venue_id=venue_id, station=station)
        db.add(row)
    row.pin_hash = hash_secret(pin)
    row.updated_by_id = actor.id
    row.updated_at = utcnow()

    record.write(
        db,
        venue_id=venue_id,
        user_id=actor.id,
        action="station.pin",
        entity=f"station:{station}",
        after={"station": station},
    )


def has_pin(db: DbSession, venue_id, station: str) -> bool:
    return (
        db.scalars(
            select(StationPin).where(
                StationPin.venue_id == venue_id, StationPin.station == station
            )
        ).first()
        is not None
    )


def station_for_pin(db: DbSession, venue_id, pin: str) -> str | None:
    """Какой станции принадлежит этот PIN.

    Станцию не спрашивают отдельно: планшет бара и планшет кухни отличаются
    как раз PIN-ом, и лишний экран выбора — это лишний способ открыть чужую
    смену.
    """
    for row in db.scalars(select(StationPin).where(StationPin.venue_id == venue_id)).all():
        if verify_secret(row.pin_hash, pin):
            return row.station
    return None


def open_shift(db: DbSession, venue_id, station: str) -> tuple[Shift, str]:
    """Открыть смену. Возвращает (смена, токен планшета).

    Уже открытая смена переиспользуется: планшет перезагрузили, а смена та же.
    """
    _close_stale(db, venue_id)
    live = current(db, venue_id, station)
    if live is not None:
        token = new_token()
        live.token_hash = token_fingerprint(token)
        return live, token

    token = new_token()
    shift = Shift(
        venue_id=venue_id,
        station=station,
        opened_at=utcnow(),
        token_hash=token_fingerprint(token),
    )
    db.add(shift)
    db.flush()
    record.write(
        db,
        venue_id=venue_id,
        user_id=None,
        action="shift.open",
        entity=f"station:{station}",
        after={"station": station},
    )
    return shift, token


def current(db: DbSession, venue_id, station: str) -> Shift | None:
    return db.scalars(
        select(Shift)
        .where(
            Shift.venue_id == venue_id,
            Shift.station == station,
            Shift.closed_at.is_(None),
        )
        .order_by(Shift.opened_at.desc())
    ).first()


def by_token(db: DbSession, token: str | None) -> Shift | None:
    if not token:
        return None
    shift = db.scalars(
        select(Shift).where(Shift.token_hash == token_fingerprint(token))
    ).first()
    if shift is None or shift.closed_at is not None:
        return None
    return shift


def close_shift(db: DbSession, shift: Shift, note: str | None = None) -> Shift:
    shift.closed_at = utcnow()
    shift.tickets_done = _counted(db, shift)
    shift.note = (note or "").strip() or None
    record.write(
        db,
        venue_id=shift.venue_id,
        user_id=None,
        action="shift.close",
        entity=f"station:{shift.station}",
        after={
            "station": shift.station,
            "tickets": shift.tickets_done,
            "minutes": int((shift.closed_at - shift.opened_at).total_seconds() // 60),
        },
    )
    return shift


def _counted(db: DbSession, shift: Shift) -> int:
    """Сколько марок станция отдала за смену."""
    end = shift.closed_at or utcnow()
    return (
        db.scalar(
            select(func.count())
            .select_from(Ticket)
            .join(Order, Order.id == Ticket.order_id)
            .join(Check, Check.id == Order.check_id)
            .where(
                Check.venue_id == shift.venue_id,
                Ticket.station == shift.station,
                Ticket.ready_at.is_not(None),
                Ticket.ready_at >= shift.opened_at,
                Ticket.ready_at <= end,
            )
        )
        or 0
    )


def _close_stale(db: DbSession, venue_id) -> None:
    """Забытая открытой смена закрывается сама.

    Иначе через неделю отчёт покажет одну смену длиной в неделю, и по нему
    нельзя будет понять ровно ничего.
    """
    limit = utcnow().timestamp() - MAX_SHIFT_HOURS * 3600
    for shift in db.scalars(
        select(Shift).where(Shift.venue_id == venue_id, Shift.closed_at.is_(None))
    ).all():
        if shift.opened_at.timestamp() < limit:
            shift.closed_at = utcnow()
            shift.tickets_done = _counted(db, shift)
            shift.note = "закрыта автоматически: планшет забыли выключить"


def payload(shift: Shift | None, station: str | None = None) -> dict:
    if shift is None:
        return {"open": False, "station": station}
    return {
        "open": shift.closed_at is None,
        "station": shift.station,
        "opened_at": shift.opened_at.isoformat(),
        "closed_at": shift.closed_at.isoformat() if shift.closed_at else None,
        "tickets_done": shift.tickets_done,
    }
