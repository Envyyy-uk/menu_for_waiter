"""Личная смена: открыть, закрыть, увидеть итог.

Табель ведёт сам человек: нажал «Открыть смену» — пошло время, нажал
«Закрыть» — время остановилось и показался итог вечера. Это не контроль, а
ответ на вопрос, который иначе всплывает в конце месяца: сколько часов было.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session as DbSession

from app.core.security import verify_secret

from app.core.deps import get_venue, require
from app.db import get_db
from app.models import User, Venue
from app.services import worktime

router = APIRouter(prefix="/api/work", tags=["табель"])


def _fail(exc: worktime.WorkError):
    raise HTTPException(
        status_code=exc.status, detail=exc.message, headers=None
    ) from None


@router.get("/shift")
def my_shift(
    actor: User = Depends(require("work.shift")),
    db: DbSession = Depends(get_db),
    venue: Venue = Depends(get_venue),
) -> dict:
    return worktime.payload(worktime.current(db, actor))


@router.post("/shift/open")
def open_shift(
    actor: User = Depends(require("work.shift")),
    db: DbSession = Depends(get_db),
    venue: Venue = Depends(get_venue),
) -> dict:
    row = worktime.open_shift(db, actor)
    db.commit()
    return worktime.payload(row)


class CloseIn(BaseModel):
    # PIN спрашивается на выходе: смену закрывает тот, кто её открыл, а не
    # тот, кому передали телефон. Час в табеле — это деньги.
    pin: str | None = None


@router.post("/shift/close")
def close_shift(
    body: CloseIn | None = None,
    actor: User = Depends(require("work.shift")),
    db: DbSession = Depends(get_db),
    venue: Venue = Depends(get_venue),
) -> dict:
    """Закрытие возвращает итог вечера — его и показывает приложение.

    Если остались открытые чеки, смена не закрывается: уйти домой с открытым
    чеком значит оставить деньги на столе.
    """
    pin = (body.pin if body else None) or ""
    if pin and not verify_secret(actor.pin_hash, pin):
        raise HTTPException(status_code=403, detail="Не тот PIN")
    try:
        row = worktime.close_shift(db, actor)
    except worktime.WorkError as exc:
        db.rollback()
        _fail(exc)
    db.commit()
    return worktime.payload(row)
