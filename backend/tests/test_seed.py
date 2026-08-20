from sqlalchemy import select

from app.models import MenuItem, Table, User
from app.models.user import ROLE_ADMIN


def test_menu_loaded(db, venue):
    items = db.scalars(select(MenuItem).where(MenuItem.venue_id == venue.id)).all()
    assert len(items) == 45
    assert {i.station for i in items} == {"bar", "kitchen"}
    # Категории показываются по-русски — интерфейс полностью русский.
    assert venue.categories["hookah"] == "Кальяны"


def test_tables_and_admin(db, venue):
    tables = db.scalars(select(Table).where(Table.venue_id == venue.id)).all()
    assert len(tables) == 12
    # Токен стола — непрозрачная строка, а не номер: иначе сосед заказывает
    # на чужой стол.
    assert all(t.token and t.token != t.label for t in tables)

    admin = db.scalars(select(User).where(User.venue_id == venue.id)).first()
    assert admin.role == ROLE_ADMIN
    assert admin.pin_hash and "1234" not in admin.pin_hash


def test_seed_keeps_stop_list(db, venue):
    """Перезапуск среди смены не возвращает в продажу то, что кончилось."""
    from app.seed import seed

    item = db.scalars(select(MenuItem).where(MenuItem.key == "mojito")).one()
    item.state = "off"
    db.commit()

    seed(db)
    db.refresh(item)
    assert item.state == "off"
