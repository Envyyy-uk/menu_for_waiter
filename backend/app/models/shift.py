import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.dialects.postgresql import UUID as PgUUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, Timestamped, UUIDPk


class StationPin(UUIDPk, Timestamped, Base):
    """PIN планшета станции.

    Отдельный от личных намеренно. Планшет стоит на полке весь вечер, за ним
    подходят все по очереди, и требовать личный PIN на каждую марку значит не
    получить ни одного нажатия. Личная ответственность здесь и не нужна:
    планшет только показывает марки и двигает их статус, к деньгам он не
    прикасается.

    А вот открыть и закрыть смену — действие смены, и оно именное по факту:
    кто ввёл PIN, тот и открыл, и это записано.
    """

    __tablename__ = "station_pins"

    venue_id: Mapped[uuid.UUID] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("venues.id", ondelete="CASCADE"), index=True
    )
    station: Mapped[str] = mapped_column(String(10), unique=True)
    pin_hash: Mapped[str] = mapped_column(String(255))
    updated_by_id: Mapped[uuid.UUID | None] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), default=None
    )
    updated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), default=None)


class Shift(UUIDPk, Timestamped, Base):
    """Смена станции: от «открыли планшет» до «закрыли».

    Нужна не ради красоты в отчёте. Открытая смена — это ответ на вопрос
    «кто-нибудь вообще смотрит на бар?»: если марки висят, а смена не открыта,
    значит планшет никто не включил, и заказы уходят в пустоту.
    """

    __tablename__ = "shifts"

    venue_id: Mapped[uuid.UUID] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("venues.id", ondelete="CASCADE"), index=True
    )
    station: Mapped[str] = mapped_column(String(10), index=True)

    opened_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    closed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), default=None, index=True
    )
    # Сколько марок прошло за смену — считается при закрытии.
    tickets_done: Mapped[int] = mapped_column(Integer, default=0)
    note: Mapped[str | None] = mapped_column(Text, default=None)

    # Токен планшета: пока смена открыта, он и есть пропуск. Хранится хешем,
    # как и всё остальное, что даёт доступ.
    token_hash: Mapped[str] = mapped_column(String(64), unique=True)
