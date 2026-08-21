import uuid
from typing import Any

from sqlalchemy import Boolean, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PgUUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, Timestamped, UUIDPk

# Станции. Марка уходит туда, где позицию готовят.
STATION_BAR = "bar"
STATION_KITCHEN = "kitchen"
STATIONS = (STATION_BAR, STATION_KITCHEN)
STATION_NAMES = {STATION_BAR: "Бар", STATION_KITCHEN: "Кухня"}

# Состояние позиции. «Стоп» — это 86 из ресторанного жаргона: кончилось.
STATE_ON = "on"
STATE_OFF = "off"
STATE_SOON = "soon"
ITEM_STATES = (STATE_ON, STATE_OFF, STATE_SOON)


def effective_state(state: str, source_state: str) -> str:
    """Что с позицией на самом деле.

    Два выключателя, и продаётся позиция, только если оба говорят «да».
    «Кончилось» сильнее «скоро»: гостю важнее точный ответ.
    """
    if STATE_OFF in (state, source_state):
        return STATE_OFF
    if STATE_SOON in (state, source_state):
        return STATE_SOON
    return STATE_ON


class MenuItem(UUIDPk, Timestamped, Base):
    __tablename__ = "menu_items"
    __table_args__ = (UniqueConstraint("venue_id", "key", name="uq_menu_item_key"),)

    venue_id: Mapped[uuid.UUID] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("venues.id", ondelete="CASCADE"), index=True
    )

    key: Mapped[str] = mapped_column(String(80))
    # Название не переводится: гость заказывает так, как напечатано в меню.
    name: Mapped[str] = mapped_column(String(200))
    description: Mapped[str] = mapped_column(Text, default="", server_default="")

    price_pence: Mapped[int] = mapped_column(Integer, default=0)
    station: Mapped[str] = mapped_column(String(10), default=STATION_BAR)
    category: Mapped[str | None] = mapped_column(String(80), default=None)
    position: Mapped[int] = mapped_column(Integer, default=0)

    # Два выключателя, а не один.
    #
    # `state` — стоп-лист заведения: кончилось прямо сейчас, ставит бар или
    # кухня со своего планшета. `source_state` — то, что говорит каталог на
    # сайте: позиция скрыта или целое меню помечено «скоро». Их нельзя
    # смешивать: иначе синхронизация снимает стоп, поставленный барменом
    # десять минут назад, а бармен возвращает в продажу то, чего в меню
    # больше нет.
    #
    # Продаётся позиция, только если оба выключателя говорят «да».
    state: Mapped[str] = mapped_column(String(10), default=STATE_ON)
    source_state: Mapped[str] = mapped_column(
        String(10), default=STATE_ON, server_default=STATE_ON
    )

    # Группы вариантов. Считает их сервер — браузер присылает, что выбрали,
    # а не сколько это стоит.
    #
    # [{"key": "size", "label": "Объём", "mode": "one", "required": true,
    #   "depends": {"group": "leaf", "value": "dark-leaf"} | null,
    #   "add_pence": 0,
    #   "choices": [{"key": "ml50", "name": "50 мл",
    #                "price_pence": 1300,     // заменяет цену позиции
    #                "add_pence": 0,          // прибавляется к цене
    #                "max_qty": 1}]}]
    #
    # mode "one"  — переключатель, один выбор из группы;
    # mode "many" — набор: миксы к крепкому, которых бывает два.
    options: Mapped[list[Any]] = mapped_column(JSONB, default=list, server_default="[]")

    # Слова, по которым официант ищет позицию: «кальян», «шиша», «пельмени».
    # Названия английские, а искать в зале удобнее по-русски.
    search_terms: Mapped[list[str]] = mapped_column(JSONB, default=list, server_default="[]")
    # Состав из каталога: [{"key": "rum", "name": "ром"}]. Из него собирается
    # склад — коктейль списывает не «коктейль», а ром, лайм, сахар и мяту.
    ingredients: Mapped[list[dict]] = mapped_column(JSONB, default=list, server_default="[]")

    # Предупреждение на марку и в чек: алкоголь и табак — по документу.
    warning: Mapped[str | None] = mapped_column(Text, default=None)

    active: Mapped[bool] = mapped_column(Boolean, default=True)
