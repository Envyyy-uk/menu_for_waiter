import secrets
import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import Boolean, DateTime, Float, ForeignKey, Integer, String, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PgUUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, Timestamped, UUIDPk

TOKEN_BYTES = 16  # → 22 символа base64url


def new_table_token() -> str:
    return secrets.token_urlsafe(TOKEN_BYTES)


class Venue(UUIDPk, Timestamped, Base):
    __tablename__ = "venues"

    key: Mapped[str] = mapped_column(String(64), unique=True)
    name: Mapped[str] = mapped_column(String(200))
    timezone: Mapped[str] = mapped_column(String(64), default="Europe/London")
    currency: Mapped[str] = mapped_column(String(3), default="GBP")

    # Подписи категорий меню: {"spirits": "Крепкое"}. Это только для показа —
    # стоп-лист ставится на позицию, а не на группу.
    categories: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict, server_default="{}")

    # Счётчики живут здесь, а не считаются как max()+1: два чека, открытые в
    # одну миллисекунду, иначе получат один номер. UPDATE … RETURNING
    # сериализует выдачу.
    check_seq: Mapped[int] = mapped_column(Integer, default=0, server_default="0")

    # Состояние синхронизации меню с сайтом: когда последний раз ходили, что
    # получилось, и метка версии каталога (ETag), чтобы не качать одно и то же.
    menu_sync: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict, server_default="{}")

    tables: Mapped[list["Table"]] = relationship(back_populates="venue")


class Table(UUIDPk, Timestamped, Base):
    """Стол зала. Открытый чек всегда привязан к столу — как в Lightspeed:
    сначала выбираешь стол, потом набираешь заказ."""

    __tablename__ = "tables"
    __table_args__ = (UniqueConstraint("venue_id", "label", name="uq_table_label"),)

    venue_id: Mapped[uuid.UUID] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("venues.id", ondelete="CASCADE"), index=True
    )
    label: Mapped[str] = mapped_column(String(40))
    # Зал, терраса, бар — группировка в сетке столов.
    zone: Mapped[str] = mapped_column(String(40), default="Зал", server_default="Зал")
    seats: Mapped[int] = mapped_column(Integer, default=4, server_default="4")
    position: Mapped[int] = mapped_column(Integer, default=0, server_default="0")

    # Место на плане зала, в долях от его ширины и высоты (0..100).
    #
    # Проценты, а не пиксели: план рисуют на ноутбуке, а смотрят на телефоне,
    # и стол у окна должен остаться у окна на любом экране.
    x: Mapped[float | None] = mapped_column(Float, default=None)
    y: Mapped[float | None] = mapped_column(Float, default=None)

    # Непрозрачная строка под QR: пригодится, если гостю снова дадут меню.
    token: Mapped[str] = mapped_column(String(64), unique=True, default=new_table_token)
    active: Mapped[bool] = mapped_column(Boolean, default=True)

    venue: Mapped[Venue] = relationship(back_populates="tables")
