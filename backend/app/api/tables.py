"""Столы зала: сетка, с которой начинается смена."""

from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.orm import Session as DbSession

from app.core.deps import get_venue, require
from app.db import get_db
from app.models import CHECK_OPEN, Check, Table, User, Venue
from app.services.checks import due, subtotal, ticket_state, total

router = APIRouter(prefix="/api/tables", tags=["зал"])


@router.get("")
def tables(
    actor: User = Depends(require("checks.view")),
    db: DbSession = Depends(get_db),
    venue: Venue = Depends(get_venue),
) -> list[dict]:
    """Сетка столов с открытыми чеками.

    На плитке видно то, ради чего на неё смотрят: занят ли стол, сколько
    висит, давно ли сидят и чей это стол.
    """
    rows = db.scalars(
        select(Table)
        .where(Table.venue_id == venue.id, Table.active.is_(True))
        .order_by(Table.zone, Table.position, Table.label)
    ).all()

    open_checks = db.scalars(
        select(Check).where(Check.venue_id == venue.id, Check.status == CHECK_OPEN)
    ).all()
    by_table: dict = {}
    for check in open_checks:
        by_table.setdefault(check.table_id, []).append(check)

    names = {u.id: u.name for u in db.scalars(select(User).where(User.venue_id == venue.id)).all()}

    out = []
    for table in rows:
        checks = sorted(by_table.get(table.id, []), key=lambda c: c.created_at)
        out.append(
            {
                "id": str(table.id),
                "label": table.label,
                "zone": table.zone,
                "seats": table.seats,
                "x": table.x,
                "y": table.y,
                "checks": [
                    {
                        "id": str(c.id),
                        "number": c.number,
                        "guests": c.guests,
                        "waiter": names.get(c.waiter_id),
                        "waiter_id": str(c.waiter_id) if c.waiter_id else None,
                        "mine": c.waiter_id == actor.id,
                        "opened_at": c.created_at.isoformat() if c.created_at else None,
                        "total_pence": total(c),
                        "subtotal_pence": subtotal(c),
                        "due_pence": due(c),
                        "has_draft": any(i.status == "draft" for i in c.items),
                        "stations": ticket_state(c),
                    }
                    for c in checks
                ],
            }
        )
    return out
