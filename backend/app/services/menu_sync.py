"""Меню приезжает с сайта само.

Каталог ведётся в одном месте — в админке гостевого меню. Раньше POS жил
снимком этого каталога, то есть меню приходилось вводить дважды; а всё, что
вводят дважды, однажды расходится — и расходится на цене, при госте.

Правила, на которых держится вся эта затея:

1. **Недоступный сайт ничего не ломает.** Не ответил, отдал мусор, отдал
   пустой каталог — меню на экране остаётся прежним. Работающее старое меню
   лучше пустого нового.
2. **Стоп-лист не трогаем.** То, что сняли час назад, синхронизация обратно
   в продажу не возвращает: она знает каталог, а не то, что кончилось.
3. **Позиции не удаляются.** Пропала из каталога — перестаёт показываться
   официанту, но остаётся в базе: на неё ссылаются закрытые чеки.
4. **Смена цены пишется в журнал.** Цена — это деньги, и неважно, поменял её
   человек или сайт.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any

import httpx
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.db import SessionLocal
from app.models import MenuItem, Venue, utcnow
from app.services import realtime
from app.services.audit import record
from app.services.catalogue import CatalogueError, convert

log = logging.getLogger("menu_sync")

TIMEOUT_SECONDS = 15


class SyncError(Exception):
    pass


# ------------------------------------------------------------- загрузка ---
def fetch(url: str, etag: str | None = None) -> tuple[dict[str, Any] | None, str | None]:
    """→ (каталог, ETag). Каталог `None` — на сайте ничего не менялось.

    ETag экономит не столько трафик, сколько нервы: без него каждая проверка
    выглядела бы в журнале как изменение меню.
    """
    headers = {"Accept": "application/json"}
    if etag:
        headers["If-None-Match"] = etag
    try:
        answer = httpx.get(url, headers=headers, timeout=TIMEOUT_SECONDS, follow_redirects=True)
    except httpx.HTTPError as exc:
        raise SyncError(f"сайт недоступен: {exc.__class__.__name__}") from None

    if answer.status_code == 304:
        return None, etag
    if answer.status_code != 200:
        raise SyncError(f"сайт ответил {answer.status_code}")
    try:
        return answer.json(), answer.headers.get("etag")
    except ValueError:
        # Прилетела страница, а не каталог. Обычно это заглушка хостинга.
        raise SyncError("вместо каталога пришёл не JSON") from None


def fetch_labels(url: str) -> dict[str, Any] | None:
    """Словарь подписей рядом с каталогом. Не приехал — не беда, есть запасной."""
    try:
        answer = httpx.get(url, timeout=TIMEOUT_SECONDS, follow_redirects=True)
        if answer.status_code == 200:
            return answer.json()
    except (httpx.HTTPError, ValueError):
        pass
    return None


# -------------------------------------------------------------- запись ----
def apply(db: Session, venue: Venue, payload: dict[str, Any], *, actor_id=None) -> dict[str, Any]:
    """Разложить каталог по базе. Возвращает отчёт о том, что изменилось."""
    items = payload.get("items") or []
    if not items:
        raise SyncError("в каталоге нет позиций")

    venue.categories = payload.get("categories") or venue.categories

    existing = {
        i.key: i for i in db.scalars(select(MenuItem).where(MenuItem.venue_id == venue.id)).all()
    }

    added: list[str] = []
    updated: list[str] = []
    price_changes: list[dict[str, Any]] = []
    seen: set[str] = set()

    for raw in items:
        key = raw["key"]
        seen.add(key)
        item = existing.get(key)
        is_new = item is None
        if is_new:
            item = MenuItem(venue_id=venue.id, key=key, state=raw.get("state", "on"))
            db.add(item)
            added.append(raw["name"])

        was = {
            "name": item.name,
            "price_pence": item.price_pence,
            "station": item.station,
            "options": item.options,
            "description": item.description,
            "category": item.category,
            "warning": item.warning,
            "search_terms": item.search_terms,
            "position": item.position,
            "active": item.active,
        }

        item.name = raw["name"]
        item.description = raw.get("description") or ""
        item.category = raw.get("category")
        item.station = raw.get("station", "bar")
        item.price_pence = int(raw.get("price_pence") or 0)
        item.position = int(raw.get("position") or 0)
        item.options = raw.get("options") or []
        item.search_terms = raw.get("search_terms") or []
        item.warning = raw.get("warning")
        item.active = True
        # `state` не трогаем намеренно: стоп-лист знает бар, а не каталог.

        if is_new:
            continue
        if any(was[field] != getattr(item, field) for field in was):
            updated.append(item.name)
        if was["price_pence"] != item.price_pence:
            price_changes.append(
                {"name": item.name, "before": was["price_pence"], "after": item.price_pence}
            )

    # Позиция, пропавшая из каталога, не удаляется: на неё ссылаются закрытые
    # чеки. Она просто перестаёт показываться официанту.
    removed = []
    for key, item in existing.items():
        if key not in seen and item.active:
            item.active = False
            removed.append(item.name)

    report = {
        "added": added,
        "updated": updated,
        "removed": removed,
        "prices": price_changes,
        "total": len(items),
    }

    # Цена — это деньги, и неважно, поменял её человек или сайт.
    for change in price_changes:
        record.write(
            db,
            venue_id=venue.id,
            user_id=actor_id,
            action="item.price_sync",
            entity=f"item:{change['name']}",
            before={"price_pence": change["before"]},
            after={"price_pence": change["after"]},
        )
    if added or removed:
        record.write(
            db,
            venue_id=venue.id,
            user_id=actor_id,
            action="menu.sync",
            entity="menu",
            after={"added": added, "removed": removed},
        )
    return report


def _remember(venue: Venue, **fields: Any) -> None:
    venue.menu_sync = {**(venue.menu_sync or {}), **fields, "at": utcnow().isoformat()}


def sync_once(db: Session, venue: Venue, *, force: bool = False, actor_id=None) -> dict[str, Any]:
    """Один заход на сайт. Ошибка сюда не поднимается — она записывается.

    Синхронизация не имеет права уронить смену: если сайт лёг, официант
    должен продолжать работать по тому меню, которое уже есть.
    """
    url = settings.menu_source_url
    if not url:
        return {"status": "off"}

    state = venue.menu_sync or {}
    try:
        raw, etag = fetch(url, None if force else state.get("etag"))
    except SyncError as exc:
        _remember(venue, status="error", error=str(exc))
        db.commit()
        log.warning("меню не обновилось: %s", exc)
        return {"status": "error", "error": str(exc)}

    if raw is None:
        _remember(venue, status="ok", error=None)
        db.commit()
        return {"status": "unchanged"}

    labels = fetch_labels(settings.menu_labels_url) if settings.menu_labels_url else None
    try:
        payload = convert(raw, labels)
        report = apply(db, venue, payload, actor_id=actor_id)
    except (CatalogueError, SyncError) as exc:
        db.rollback()
        db.refresh(venue)
        _remember(venue, status="error", error=str(exc))
        db.commit()
        log.warning("каталог непригоден: %s", exc)
        return {"status": "error", "error": str(exc)}

    _remember(venue, status="ok", error=None, etag=etag, report=report)
    db.commit()

    changed = report["added"] or report["updated"] or report["removed"]
    if changed:
        # Официант не должен продавать по вчерашнему меню: телефоны
        # перечитывают его сразу.
        realtime.publish(realtime.CHANNEL_ALL, {"type": "menu.changed"})
        log.info(
            "меню обновилось: +%s ~%s -%s",
            len(report["added"]),
            len(report["updated"]),
            len(report["removed"]),
        )
    return {"status": "ok", "report": report}


def status(venue: Venue) -> dict[str, Any]:
    state = dict(venue.menu_sync or {})
    state.pop("etag", None)   # служебное, смотреть не на что
    return {
        "enabled": bool(settings.menu_source_url),
        "url": settings.menu_source_url,
        "every_minutes": settings.menu_sync_minutes,
        **state,
    }


# --------------------------------------------------------------- фоном ----
async def run_forever() -> None:
    """Фоновая проверка. Живёт рядом с сервером и молчит, пока всё хорошо."""
    if not settings.menu_source_url or settings.menu_sync_minutes <= 0:
        return
    delay = settings.menu_sync_minutes * 60
    while True:
        try:
            await asyncio.to_thread(_tick)
        except Exception:  # noqa: BLE001 — фон не имеет права ронять сервер
            log.warning("проверка меню сорвалась", exc_info=True)
        await asyncio.sleep(delay)


def _tick() -> None:
    with SessionLocal() as db:
        venue = db.scalars(select(Venue).order_by(Venue.created_at)).first()
        if venue is not None:
            sync_once(db, venue)
