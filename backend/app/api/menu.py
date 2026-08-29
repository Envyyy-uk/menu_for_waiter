"""Меню для официанта. Один ответ, из которого рисуется весь экран."""

from __future__ import annotations

import json
import uuid
from datetime import timedelta

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session as DbSession

from app.core.deps import current_user, get_venue, require
from app.db import get_db
from app.models import (
    ITEM_CANCELLED,
    ITEM_STATES,
    STATION_BAR,
    STATION_NAMES,
    STATIONS,
    Check,
    CheckItem,
    MenuItem,
    User,
    Venue,
    utcnow,
)
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
        # Своя позиция: её завели здесь, а не привезли с сайта. Значит, её
        # можно и убрать отсюда — а сайтовую нельзя.
        "local": item.local,
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
    habits = usual(db, venue.id, {i.id for i in items})
    return {
        "currency": venue.currency,
        # Порядок категорий — порядок первого появления позиции: так же, как
        # в печатном меню, к которому официант привык.
        "categories": [
            {"key": key, "name": venue.categories.get(key, key)}
            for key in dict.fromkeys(i.category for i in items if i.category)
        ],
        "items": [item_payload(i) for i in items],
        # Что берут чаще всего и с какими вариантами. В полный зал ищут не по
        # каталогу, а по памяти: половина заказов — одни и те же десять
        # позиций, и листать до них весь список неоткуда.
        **habits,
    }


# За сколько дней смотрим привычки заведения. Две недели — это и будни, и
# выходные, но ещё не прошлый сезон: летом пьют не то же, что зимой.
HABIT_DAYS = 14
POPULAR_MAX = 10


def usual(db: DbSession, venue_id, live: set) -> dict:
    """Что берут чаще всего и с какими вариантами.

    Считается по проданному, а не по чьему-то мнению: список сам едет за
    сезоном и за тем, что в заведении реально заказывают.

    Отменённое не считается: гость передумал — значит, это не привычка.
    """
    since = utcnow() - timedelta(days=HABIT_DAYS)
    rows = db.execute(
        select(CheckItem.menu_item_id, CheckItem.options_keys, CheckItem.qty)
        .join(Check, Check.id == CheckItem.check_id)
        .where(
            Check.venue_id == venue_id,
            CheckItem.created_at >= since,
            CheckItem.status != ITEM_CANCELLED,
            CheckItem.menu_item_id.is_not(None),
        )
    ).all()

    counts: dict = {}
    variants: dict = {}
    for item_id, options, qty in rows:
        if item_id not in live:
            continue
        counts[item_id] = counts.get(item_id, 0) + (qty or 1)
        # Ключ варианта — сам выбор. Списки (миксы) приводим к строке в
        # исходном порядке: «кола, кола» и «кола, спрайт» — разные привычки.
        key = json.dumps(options or {}, sort_keys=True, ensure_ascii=False)
        seen = variants.setdefault(item_id, {})
        seen[key] = seen.get(key, 0) + (qty or 1)

    popular = sorted(counts, key=lambda i: -counts[i])[:POPULAR_MAX]
    habit = {}
    for item_id, seen in variants.items():
        best, times = max(seen.items(), key=lambda kv: kv[1])
        chosen = json.loads(best)
        # Пустой выбор подсказывать нечего, и одного раза мало для «обычно».
        if chosen and times >= 2:
            habit[str(item_id)] = chosen
    return {"popular": [str(i) for i in popular], "usual": habit}


class OwnItemIn(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    price_pence: int = Field(ge=0, le=10_000_00)
    category: str = Field(min_length=1, max_length=40)
    station: str = STATION_BAR
    description: str = ""


@router.post("/items", status_code=201)
def add_own_item(
    body: OwnItemIn,
    actor: User = Depends(require("items.edit")),
    db: DbSession = Depends(get_db),
    venue: Venue = Depends(get_venue),
) -> dict:
    """Своя позиция — та, которой на сайте нет.

    В баре всегда есть то, чего в гостевом меню не печатают: джин-тоник,
    который проще нажать одной кнопкой, чем набирать джин и тоник по
    отдельности, — и списывать тогда тоже одной кнопкой, сразу с двух полок.

    Ключ с приставкой: он не должен столкнуться с сайтовым, даже если там
    когда-нибудь появится позиция с тем же именем.
    """
    if body.station not in STATIONS:
        raise HTTPException(status_code=422, detail="Станция — только бар или кухня")

    base = "".join(c if c.isalnum() else "-" for c in body.name.lower()).strip("-")
    key = f"own:{base or uuid.uuid4().hex[:8]}"
    if db.scalars(
        select(MenuItem).where(MenuItem.venue_id == venue.id, MenuItem.key == key)
    ).first():
        key = f"{key}-{uuid.uuid4().hex[:4]}"

    last = db.scalars(
        select(MenuItem.position)
        .where(MenuItem.venue_id == venue.id)
        .order_by(MenuItem.position.desc())
    ).first()

    item = MenuItem(
        venue_id=venue.id,
        key=key,
        name=body.name.strip(),
        description=body.description.strip(),
        category=body.category,
        station=body.station,
        price_pence=body.price_pence,
        position=(last or 0) + 1,
        local=True,
        active=True,
    )
    db.add(item)
    db.flush()
    record.write(
        db,
        venue_id=venue.id,
        user_id=actor.id,
        action="item.own.add",
        entity=f"item:{item.name}",
        after={"name": item.name, "price_pence": item.price_pence},
    )
    db.commit()
    realtime.publish(realtime.CHANNEL_ALL, {"type": "menu.changed"})
    return item_payload(item)


@router.delete("/items/{item_id}")
def drop_own_item(
    item_id: uuid.UUID,
    actor: User = Depends(require("items.edit")),
    db: DbSession = Depends(get_db),
    venue: Venue = Depends(get_venue),
) -> dict:
    """Убрать свою позицию.

    Не удаляем: на неё ссылаются закрытые чеки, и отчёт за прошлый месяц
    должен знать, что продали. Просто перестаёт показываться — так же, как
    позиция, пропавшая с сайта.
    """
    item = db.get(MenuItem, item_id)
    if item is None or item.venue_id != venue.id:
        raise HTTPException(status_code=404, detail="Позиции нет")
    if not item.local:
        raise HTTPException(
            status_code=409,
            detail="Эта позиция с сайта — убирают её там, здесь можно только в стоп",
        )
    item.active = False
    record.write(
        db,
        venue_id=venue.id,
        user_id=actor.id,
        action="item.own.drop",
        entity=f"item:{item.name}",
        before={"name": item.name},
    )
    db.commit()
    realtime.publish(realtime.CHANNEL_ALL, {"type": "menu.changed"})
    return {"status": "ok"}


class StateIn(BaseModel):
    state: str


class CategoryStateIn(BaseModel):
    category: str
    state: str


@router.post("/category/state")
def set_category_state(
    body: CategoryStateIn,
    actor: User = Depends(require("items.state")),
    db: DbSession = Depends(get_db),
    venue: Venue = Depends(get_venue),
) -> dict:
    """Стоп на целый раздел.

    Кончился газ — встали все кальяны, а не один. Снимать стоп с двенадцати
    позиций по одной, когда газ привезли, — то же самое наоборот.
    """
    if body.state not in ITEM_STATES:
        raise HTTPException(status_code=422, detail="неизвестное состояние")
    items = db.scalars(
        select(MenuItem).where(
            MenuItem.venue_id == venue.id,
            MenuItem.category == body.category,
            MenuItem.active.is_(True),
        )
    ).all()
    if not items:
        raise HTTPException(status_code=404, detail="в разделе нет позиций")

    for item in items:
        item.state = body.state
    record.write(
        db,
        venue_id=venue.id,
        user_id=actor.id,
        action="category.state",
        entity=f"category:{body.category}",
        after={"state": body.state, "count": len(items)},
    )
    db.commit()
    realtime.publish(realtime.CHANNEL_ALL, {"type": "menu.state", "category": body.category})
    return {"category": body.category, "state": body.state, "count": len(items)}


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
