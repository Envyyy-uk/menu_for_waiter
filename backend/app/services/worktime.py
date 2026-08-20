"""Табель: сколько человек отработал.

Отчёт по смене отвечает «сколько заведение заработало». Этот файл — про
другое: «сколько отработал вот этот человек», потому что зарплату платят за
часы, а не за выручку.

Три решения, которые здесь приняты сознательно:

* **Считаются минуты, а не часы.** Округление до часа в обе стороны — это
  чужие деньги, и спорить о них потом будет нечем.
* **Итог складывается снимком.** Через полгода пересчитать его не по чему:
  цены поменяются, чеки закроются, человек уволится. Снимок отвечает, что
  было в тот вечер, ровно так, как это выглядело в тот вечер.
* **Хранится год.** Меньше — не с чем сверить спорную зарплату; больше —
  незачем, это перестаёт быть оперативными данными.
"""

from __future__ import annotations

from datetime import timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session as DbSession

from app.models import (
    CHECK_CLOSED,
    CHECK_OPEN,
    ITEM_CANCELLED,
    PAY_CARD,
    PAY_CASH,
    Check,
    Table,
    User,
    WorkShift,
    utcnow,
)
from app.services.audit import record

# Смену забыли закрыть — она не висит вечно и не копит часы за ночь: столько
# не работает никто, и такой табель врёт хуже, чем пустой.
MAX_HOURS = 16
KEEP_DAYS = 365


class WorkError(Exception):
    def __init__(self, message: str, status: int = 409, extra: dict | None = None):
        super().__init__(message)
        self.message = message
        self.status = status
        self.extra = extra or {}


def hours_text(minutes: int) -> str:
    """«7 ч 20 мин» — так это читают, а не 7.33."""
    hours, rest = divmod(max(0, minutes), 60)
    if not hours:
        return f"{rest} мин"
    if not rest:
        return f"{hours} ч"
    return f"{hours} ч {rest} мин"


def current(db: DbSession, user: User) -> WorkShift | None:
    """Открытая смена этого человека, если она есть.

    Заодно закрывает просроченную: телефон унесли домой, смену не закрыли, и
    к утру в табеле было бы четырнадцать часов сна.
    """
    row = db.scalars(
        select(WorkShift)
        .where(WorkShift.user_id == user.id, WorkShift.closed_at.is_(None))
        .order_by(WorkShift.opened_at.desc())
    ).first()
    if row is None:
        return None

    if utcnow() - row.opened_at > timedelta(hours=MAX_HOURS):
        _finish(db, row, user, auto=True)
        db.commit()
        return None
    return row


def open_shift(db: DbSession, user: User) -> WorkShift:
    live = current(db, user)
    if live is not None:
        # Открыть вторую смену поверх первой — верный способ получить два
        # табеля за один вечер. Возвращаем ту, что уже идёт.
        return live

    row = WorkShift(
        venue_id=user.venue_id,
        user_id=user.id,
        name_snapshot=user.name,
        role_snapshot=user.role,
        opened_at=utcnow(),
    )
    db.add(row)
    db.flush()
    record.write(
        db,
        venue_id=user.venue_id,
        user_id=user.id,
        action="work.open",
        entity=f"user:{user.id}",
        after={"name": user.name},
    )
    return row


def open_checks(db: DbSession, user: User) -> list[str]:
    """Столы, на которых у человека остались открытые чеки."""
    rows = db.scalars(
        select(Check).where(
            Check.venue_id == user.venue_id,
            Check.waiter_id == user.id,
            Check.status == CHECK_OPEN,
        )
    ).all()
    labels = {
        t.id: t.label
        for t in db.scalars(select(Table).where(Table.venue_id == user.venue_id)).all()
    }
    return sorted({labels.get(c.table_id, "—") for c in rows})


def close_shift(db: DbSession, user: User) -> WorkShift:
    row = current(db, user)
    if row is None:
        raise WorkError("Смена не открыта", status=409)

    left = open_checks(db, user)
    if left:
        # Уйти домой с открытым чеком — значит оставить деньги на столе.
        # Передать стол может менеджер, закрыть — сам официант.
        raise WorkError(
            "Сначала закройте чеки: " + ", ".join(f"стол {t}" for t in left),
            status=409,
            extra={"tables": left},
        )

    _finish(db, row, user, auto=False)
    _prune(db, user.venue_id)
    return row


def _finish(db: DbSession, row: WorkShift, user: User, *, auto: bool) -> None:
    row.closed_at = utcnow()
    row.minutes = max(0, int((row.closed_at - row.opened_at).total_seconds() // 60))
    if auto:
        # Забытая смена не должна выглядеть как отработанная ночь.
        row.minutes = min(row.minutes, MAX_HOURS * 60)
    row.report = summary(db, user, row)
    row.report["auto_closed"] = auto
    record.write(
        db,
        venue_id=user.venue_id,
        user_id=user.id,
        action="work.close",
        entity=f"user:{user.id}",
        after={
            "name": user.name,
            "minutes": row.minutes,
            "hours": hours_text(row.minutes),
            "auto": auto,
        },
    )


def summary(db: DbSession, user: User, row: WorkShift) -> dict:
    """Что человек сделал за эту смену.

    Считается по чекам, которые вёл он: стол его — значит и выручка его. Не
    по тому, кто нажал «оплата»: подменить у терминала может кто угодно.
    """
    until = row.closed_at or utcnow()
    checks = db.scalars(
        select(Check).where(
            Check.venue_id == user.venue_id,
            Check.waiter_id == user.id,
            Check.status == CHECK_CLOSED,
            Check.closed_at >= row.opened_at,
            Check.closed_at <= until,
        )
    ).all()

    cash = card = revenue = discount = 0
    cancelled_count = cancelled_sum = 0
    guests = 0
    for check in checks:
        guests += check.guests
        discount += check.discount_pence or 0
        for pay in check.payments:
            revenue += pay.amount_pence
            if pay.method == PAY_CASH:
                cash += pay.amount_pence
            elif pay.method == PAY_CARD:
                card += pay.amount_pence
        for item in check.items:
            if item.status == ITEM_CANCELLED:
                cancelled_count += 1
                cancelled_sum += item.unit_price_pence * item.qty

    minutes = row.minutes or max(0, int((until - row.opened_at).total_seconds() // 60))
    return {
        "opened_at": row.opened_at.isoformat(),
        "closed_at": row.closed_at.isoformat() if row.closed_at else None,
        "minutes": minutes,
        "hours_text": hours_text(minutes),
        "checks": len(checks),
        "guests": guests,
        "revenue_pence": revenue,
        "cash_pence": cash,
        "card_pence": card,
        "discount_pence": discount,
        "average_pence": revenue // len(checks) if checks else 0,
        "cancelled": {"count": cancelled_count, "amount_pence": cancelled_sum},
    }


def payload(row: WorkShift | None) -> dict:
    if row is None:
        return {"open": False}
    minutes = row.minutes or max(0, int((utcnow() - row.opened_at).total_seconds() // 60))
    return {
        "open": row.closed_at is None,
        "id": str(row.id),
        "name": row.name_snapshot,
        "opened_at": row.opened_at.isoformat(),
        "closed_at": row.closed_at.isoformat() if row.closed_at else None,
        "minutes": minutes,
        "hours_text": hours_text(minutes),
        "report": row.report or {},
    }


def _prune(db: DbSession, venue_id) -> None:
    """Год — и хватит. Дальше это уже не табель, а склад мусора."""
    edge = utcnow() - timedelta(days=KEEP_DAYS)
    old = db.scalars(
        select(WorkShift).where(
            WorkShift.venue_id == venue_id,
            WorkShift.closed_at.is_not(None),
            WorkShift.closed_at < edge,
        )
    ).all()
    for row in old:
        db.delete(row)
