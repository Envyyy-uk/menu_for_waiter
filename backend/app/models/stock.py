import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import Boolean, DateTime, ForeignKey, Numeric, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PgUUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, Timestamped, UUIDPk

# Единицы. Их немного намеренно: чем длиннее список, тем чаще выбирают не то.
UNIT_ML = "ml"
UNIT_G = "g"
UNIT_PC = "pc"
UNITS = (UNIT_ML, UNIT_G, UNIT_PC)
UNIT_NAMES = {UNIT_ML: "мл", UNIT_G: "г", UNIT_PC: "шт"}

# Откуда взялось движение по складу.
MOVE_IN = "in"            # приход: привезли
MOVE_SALE = "sale"        # продажа: позиция ушла на станцию
MOVE_RETURN = "return"    # возврат: позицию отменили
MOVE_WRITE_OFF = "off"    # списание: разбили, испортилось
MOVE_COUNT = "count"      # инвентаризация: пересчитали руками
MOVE_REASONS = (MOVE_IN, MOVE_SALE, MOVE_RETURN, MOVE_WRITE_OFF, MOVE_COUNT)
MOVE_NAMES = {
    MOVE_IN: "Приход",
    MOVE_SALE: "Продажа",
    MOVE_RETURN: "Возврат",
    MOVE_WRITE_OFF: "Списание",
    MOVE_COUNT: "Инвентаризация",
}


class StockItem(UUIDPk, Timestamped, Base):
    """Что лежит на полке.

    Склад намеренно отдельный от меню: в меню «Absolut, Stoli» — одна позиция
    с вариантами, а на полке это две разные бутылки, и кончаются они порознь.
    """

    __tablename__ = "stock_items"
    __table_args__ = (UniqueConstraint("venue_id", "name", name="uq_stock_name"),)

    venue_id: Mapped[uuid.UUID] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("venues.id", ondelete="CASCADE"), index=True
    )
    name: Mapped[str] = mapped_column(String(160))
    unit: Mapped[str] = mapped_column(String(4), default=UNIT_PC)

    # Дробное количество: 0.5 бутылки не бывает, а 37.5 мл — бывает каждый
    # вечер. Numeric, а не float: остаток это деньги, и округления в нём
    # накапливаются.
    quantity: Mapped[float] = mapped_column(Numeric(12, 3), default=0)
    # Порог, ниже которого пора заказывать.
    low_at: Mapped[float] = mapped_column(Numeric(12, 3), default=0)

    note: Mapped[str | None] = mapped_column(Text, default=None)
    active: Mapped[bool] = mapped_column(Boolean, default=True)


class Recipe(UUIDPk, Base):
    """Сколько чего уходит с полки на одну проданную позицию.

    Привязка не к позиции меню, а к позиции **с вариантами**: 50 мл водки и
    бутылка — это одна строка меню и совсем разный расход. Поэтому здесь
    хранится и выбор варианта.
    """

    __tablename__ = "recipes"

    venue_id: Mapped[uuid.UUID] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("venues.id", ondelete="CASCADE"), index=True
    )
    menu_item_id: Mapped[uuid.UUID] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("menu_items.id", ondelete="CASCADE"), index=True
    )
    stock_item_id: Mapped[uuid.UUID] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("stock_items.id", ondelete="CASCADE"), index=True
    )
    # {"size": "ml50"} — правило срабатывает только на этот выбор.
    # Пустой словарь означает «на любой».
    options: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict, server_default="{}")
    per_unit: Mapped[float] = mapped_column(Numeric(12, 3), default=0)
    # «Сколько выбрал официант, столько и списать».
    #
    # Иначе на одну бутылку нужно семь правил: 50, 100, 150, 200, 250, 300 и
    # сама бутылка. Объём берётся из выбранного варианта — `ml50` это 50 мл, —
    # а `per_unit` остаётся размером бутылки для варианта, где объёма нет.
    by_volume: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false")


class StockMove(UUIDPk, Base):
    """Движение по складу. Остаток — это сумма движений, а не отдельное число,
    которое кто-то правит: иначе на вопрос «куда делось» ответить нечем."""

    __tablename__ = "stock_moves"

    venue_id: Mapped[uuid.UUID] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("venues.id", ondelete="CASCADE"), index=True
    )
    stock_item_id: Mapped[uuid.UUID] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("stock_items.id", ondelete="CASCADE"), index=True
    )
    delta: Mapped[float] = mapped_column(Numeric(12, 3))
    reason: Mapped[str] = mapped_column(String(10), index=True)

    check_item_id: Mapped[uuid.UUID | None] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("check_items.id", ondelete="SET NULL"), default=None
    )
    by_id: Mapped[uuid.UUID | None] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), default=None
    )
    note: Mapped[str | None] = mapped_column(Text, default=None)
    at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
