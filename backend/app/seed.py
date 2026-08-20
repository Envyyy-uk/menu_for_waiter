"""Первый запуск: заведение, меню, столы и администратор.

Идемпотентен. Меню обновляется по ключу позиции: цену и название сидер
перезапишет, а состояние (стоп-лист) — нет. Иначе перезапуск контейнера
среди смены возвращал бы в продажу то, что кончилось час назад.
"""

from __future__ import annotations

import json
import logging

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.security import hash_secret
from app.db import SessionLocal
from app.models import MenuItem, Table, User, Venue
from app.models.user import ROLE_ADMIN

log = logging.getLogger("seed")


def _venue(db: Session, data: dict) -> Venue:
    venue = db.scalars(select(Venue).where(Venue.key == data["key"])).first()
    if venue is None:
        venue = Venue(key=data["key"])
        db.add(venue)
    venue.name = data["name"]
    venue.timezone = data.get("timezone", "Europe/London")
    venue.currency = data.get("currency", "GBP")
    db.flush()
    return venue


def _menu(db: Session, venue: Venue, payload: dict) -> int:
    venue.categories = payload.get("categories", {})
    existing = {
        i.key: i for i in db.scalars(select(MenuItem).where(MenuItem.venue_id == venue.id)).all()
    }
    seen = set()
    for raw in payload["items"]:
        item = existing.get(raw["key"])
        if item is None:
            item = MenuItem(venue_id=venue.id, key=raw["key"], state=raw.get("state", "on"))
            db.add(item)
        # Состояние не трогаем: то, что сняли со стопа руками, сидер обратно
        # в продажу не возвращает.
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
        seen.add(raw["key"])

    # Позиция, пропавшая из каталога, не удаляется: на неё ссылаются старые
    # чеки. Она просто перестаёт показываться официанту.
    for key, item in existing.items():
        if key not in seen:
            item.active = False
    return len(seen)


def _tables(db: Session, venue: Venue, count: int) -> int:
    have = {t.label for t in db.scalars(select(Table).where(Table.venue_id == venue.id)).all()}
    added = 0
    for n in range(1, count + 1):
        label = str(n)
        if label in have:
            continue
        db.add(Table(venue_id=venue.id, label=label, zone="Зал", position=n))
        added += 1
    return added


def _admin(db: Session, venue: Venue) -> User | None:
    """Первый администратор. Если сотрудники уже есть — не трогаем ничего:
    сидер не должен подсовывать известный PIN в работающее заведение."""
    if db.scalars(select(User).where(User.venue_id == venue.id)).first() is not None:
        return None
    user = User(
        venue_id=venue.id,
        name=settings.seed_admin_name,
        role=ROLE_ADMIN,
        pin_hash=hash_secret(settings.seed_admin_pin),
    )
    db.add(user)
    return user


def seed(db: Session) -> Venue:
    payload = json.loads(settings.seed_file.read_text(encoding="utf-8"))
    venue = _venue(db, payload["venue"])
    items = _menu(db, venue, payload)
    tables = _tables(db, venue, settings.seed_tables)
    admin = _admin(db, venue)
    db.commit()

    log.info("меню: %s позиций, столов добавлено: %s", items, tables)
    if admin is not None:
        log.warning(
            "создан администратор «%s», PIN — %s. Смените его в админке.",
            admin.name,
            settings.seed_admin_pin,
        )
    return venue


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    with SessionLocal() as db:
        seed(db)


if __name__ == "__main__":
    main()
