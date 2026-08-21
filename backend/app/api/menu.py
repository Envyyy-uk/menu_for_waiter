"""Меню для официанта. Один ответ, из которого рисуется весь экран."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session as DbSession

from app.core.deps import current_user, get_venue, require
from app.db import get_db
from app.models import ITEM_STATES, STATION_NAMES, MenuItem, User, Venue
from app.models.menu import effective_state
from app.services import realtime
from app.services.audit import record

router = APIRouter(prefix="/api/menu", tags=["меню"])


def item_payload(item: MenuItem) -> dict:
    return {
        "id": str(item.id),
        "key": item.key,
        "name": item.name,
        "description": item.description or "",
        "category": item.category,
        "station": item.station,
        "station_name": STATION_NAMES.get(item.station, item.station),
        "price_pence": item.price_pence,
        # Итоговое состояние: стоп-лист заведения и то, что говорит сайт.
        # Продаётся, только если оба выключателя за.
        "state": effective_state(item.state, item.source_state),
        "local_state": item.state,
        "source_state": item.source_state,
        "options": item.options or [],
        "search_terms": item.search_terms or [],
        "warning": item.warning,
    }


@router.get("")
def menu(
    user: User = Depends(current_user),
    db: DbSession = Depends(get_db),
    venue: Venue = Depends(get_venue),
) -> dict:
    items = db.scalars(
        select(MenuItem)
        .where(MenuItem.venue_id == venue.id, MenuItem.active.is_(True))
        .order_by(MenuItem.position)
    ).all()
    return {
        "currency": venue.currency,
        # Порядок категорий — порядок первого появления позиции: так же, как
        # в печатном меню, к которому официант привык.
        "categories": [
            {"key": key, "name": venue.categories.get(key, key)}
            for key in dict.fromkeys(i.category for i in items if i.category)
        ],
        "items": [item_payload(i) for i in items],
    }


class StateIn(BaseModel):
    state: str


@router.post("/{item_id}/state")
def set_state(
    item_id: str,
    body: StateIn,
    actor: User = Depends(require("items.state")),
    db: DbSession = Depends(get_db),
    venue: Venue = Depends(get_venue),
) -> dict:
    """Стоп-лист. Ставит и бар, и кухня: кончилось у них, а не у менеджера,
    и ждать его через весь зал — это ещё десять заказов того, чего нет."""
    if body.state not in ITEM_STATES:
        raise HTTPException(status_code=422, detail="неизвестное состояние")
    item = db.get(MenuItem, item_id)
    if item is None or item.venue_id != venue.id:
        raise HTTPException(status_code=404, detail="позиция не найдена")

    before = item.state
    item.state = body.state
    record.write(
        db,
        venue_id=venue.id,
        user_id=actor.id,
        action="item.state",
        entity=f"item:{item.key}",
        before={"state": before},
        after={"state": item.state},
    )
    db.commit()
    # Стоп-лист виден всем сразу: официант не должен продавать то, что
    # кончилось минуту назад.
    realtime.publish(realtime.CHANNEL_ALL, {"type": "menu.state", "key": item.key})
    return item_payload(item)
