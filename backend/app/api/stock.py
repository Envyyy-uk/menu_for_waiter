"""Склад: остатки, движения и рецепты.

Доступ только у владельца и администратора: остаток на полке — это деньги,
и правит его тот, кто за них отвечает.
"""

from __future__ import annotations

import uuid
from decimal import Decimal

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session as DbSession

from app.core.deps import get_venue, require
from app.db import get_db
from app.models import (
    MOVE_COUNT,
    MOVE_IN,
    MOVE_NAMES,
    MOVE_REASONS,
    MOVE_WRITE_OFF,
    STATION_BAR,
    UNIT_G,
    UNIT_ML,
    UNIT_NAMES,
    UNIT_PC,
    UNITS,
    MenuItem,
    Recipe,
    StockItem,
    StockMove,
    User,
    Venue,
)
from app.services import realtime, stock
from app.services.stock import SIZE_GROUPS
from app.services.audit import record

router = APIRouter(prefix="/api/stock", tags=["склад"])


def _item(db: DbSession, venue: Venue, item_id: uuid.UUID) -> StockItem:
    row = db.get(StockItem, item_id)
    if row is None or row.venue_id != venue.id:
        raise HTTPException(status_code=404, detail="позиции склада нет")
    return row


@router.get("")
def listing(
    actor: User = Depends(require("stock.view")),
    db: DbSession = Depends(get_db),
    venue: Venue = Depends(get_venue),
) -> dict:
    rows = db.scalars(
        select(StockItem).where(StockItem.venue_id == venue.id).order_by(StockItem.name)
    ).all()
    seen = stock.touched(db, venue.id)
    items = [stock.item_payload(i, seen) for i in rows if i.active]
    return {
        "units": [{"key": u, "name": UNIT_NAMES[u]} for u in UNITS],
        "items": items,
        # Сводка вперёд списка: ради неё склад и открывают. Позиции, которые
        # ещё не заполняли, сюда не попадают: ноль без движений — это «не
        # считали», а не «кончилось».
        "out": [i["name"] for i in items if i["state"] == "out"],
        "low": [i["name"] for i in items if i["state"] == "low"],
        "new": [i["name"] for i in items if i["state"] == "new"],
    }


# Что готовят на месте, а что покупают готовым.
#
# Состав есть у всего — у банки колы он тоже написан на этикетке. Но на полке
# лежит банка, а не «газированная вода, сахар и кофеин»: разбирать её на
# составляющие значит завести склад, которого не существует.
#
# Разбираем только то, что собирают руками: коктейли и кухню.
MADE_HERE = ("cocktails", "pizza", "traditional", "desserts", "platters")

# Что стоит на полке бутылкой и наливается. Считается миллилитрами, даже
# если в меню продаётся только целиком: бутылка водки остаётся бутылкой
# водки, а «1 шт» перестанет сходиться в тот день, когда рядом появится
# 50 мл — и не скажет об этом, просто начнёт списывать бутылку за порцию.
POURED = ("spirits", "wine")

# Сколько миллилитров в бутылке по умолчанию. Цифру потом правят руками —
# важно, чтобы правило вообще было, а не чтобы оно было точным с первой
# секунды. У вина бутылка своя, 0,75.
BOTTLE_ML = 700
WINE_BOTTLE_ML = 750


@router.post("/fill", status_code=201)
def fill(
    actor: User = Depends(require("stock.edit")),
    db: DbSession = Depends(get_db),
    venue: Venue = Depends(get_venue),
) -> dict:
    """Завести склад по меню.

    Заполнять руками сорок позиций — вечер работы, и на середине бросают.

    Разбирается три случая, и они разные:

    * **То, что наливают** — крепкое и вино. В миллилитрах, правило одно:
      сколько выбрали, столько и ушло. Выбрали «Бутылку» — ушла бутылка.
      Считается так и тогда, когда в меню одна только бутылка: на полке это
      всё равно бутылка водки, и «1 шт» сломается в тот день, когда рядом
      появится порция.
    * **Позиция с составом** (коктейль, пицца) — списывается не она сама, а
      её состав: ром, лайм, сахар, мята. Расход по каждому продукту вписывает
      человек: сколько мяты в мохито, каталог не знает.
    * **Всё остальное** — поштучно: банка колы уходит банкой.

    Количество везде остаётся нулевым: сколько стоит на полке, знает только
    тот, кто туда посмотрел.

    Повторный запуск чинит правила, заведённые штучными там, где надо
    наливать, — но только пока по этой позиции не считали остаток.
    """
    items = db.scalars(
        select(MenuItem).where(MenuItem.venue_id == venue.id, MenuItem.active.is_(True))
    ).all()
    have_names = {
        i.name: i
        for i in db.scalars(select(StockItem).where(StockItem.venue_id == venue.id)).all()
    }
    have_rules: dict = {}
    for r in db.scalars(select(Recipe).where(Recipe.venue_id == venue.id)).all():
        have_rules.setdefault(r.menu_item_id, []).append(r)

    made_items = 0
    made_rules = 0
    blank = 0
    fixed = 0

    def line(name: str, unit: str) -> StockItem:
        nonlocal made_items
        row = have_names.get(name)
        if row is None:
            row = StockItem(venue_id=venue.id, name=name, unit=unit, quantity=0, low_at=0)
            db.add(row)
            db.flush()
            have_names[name] = row
            made_items += 1
        return row

    def bottle_ml(item: MenuItem) -> int:
        return WINE_BOTTLE_ML if item.category == "wine" else BOTTLE_ML

    def pours(item: MenuItem) -> bool:
        """Наливается ли это с полки.

        Не по тому, есть ли в меню «50 мл»: у Grey Goose в меню одна только
        бутылка, но на полке это та же бутылка водки. Считать её штукой
        значит поймать ошибку в тот день, когда в меню добавят порцию, —
        и не заметить, потому что списываться начнёт бутылка за каждые 50 мл.
        """
        if item.category in POURED:
            return True
        return any(
            str(choice.get("key", "")).startswith("ml")
            for group in (item.options or [])
            for choice in (group.get("choices") or [])
        )

    # Вариант, названный так же, как позиция меню, — это она и есть. Микс
    # «Cola» к водке и есть та банка колы, что стоит в меню отдельной строкой.
    by_key = {i.key: i for i in items if i.key}

    def mixers(item: MenuItem, existing: list[Recipe]) -> int:
        """Правила на варианты, которые сами лежат на полке.

        Без них микс не списывается вовсе: банку колы, взятую к водке, склад
        не видит. Заводить это руками — семь напитков на восемнадцать бутылок,
        сто двадцать шесть правил; никто их не заведёт.

        Считаются и у позиции, правила которой уже есть: миксы могли появиться
        на сайте позже самой бутылки, и пропускать её целиком значит оставить
        половину меню без списания навсегда.

        Связываем только там, где вариант совпал с позицией меню по ключу:
        «дарк-лиф» и «50 мл» ничем на полке не являются.
        """
        was = {
            tuple(sorted((r.options or {}).items()))
            for r in existing
            if r.options
        }
        added = 0
        for group in item.options or []:
            key = str(group.get("key") or "")
            if not key or key in SIZE_GROUPS:
                continue
            for choice in group.get("choices") or []:
                other = by_key.get(str(choice.get("key") or ""))
                if other is None or other.id == item.id:
                    continue
                pair = ((key, str(choice.get("key"))),)
                if pair in was:
                    continue
                shelf = line(other.name, UNIT_PC)
                # Банка уходит банкой — одна штука. А сколько сока наливают в
                # микс, знает только бармен: ноль честнее выдуманной цифры и
                # виден в списке как «без расхода».
                db.add(
                    Recipe(
                        venue_id=venue.id,
                        menu_item_id=item.id,
                        stock_item_id=shelf.id,
                        options={key: choice.get("key")},
                        per_unit=1 if shelf.unit == UNIT_PC else 0,
                    )
                )
                added += 1
                was.add(pair)
        return added

    for item in items:
        # Свою позицию заготовка не трогает. Джин-тоник — это две полки сразу,
        # джин и тоник, и «одна штука джин-тоника» на складе не стоит: правило
        # для него пишут руками, ради этого его и заводят.
        if item.local:
            continue

        by_volume = pours(item)
        existing = have_rules.get(item.id, [])
        # Миксы добираются всегда: и у новой позиции, и у той, что заводили
        # раньше, когда этих правил ещё не делали.
        made_rules += mixers(item, existing)

        # У позиции уже есть правила — её заводили раньше, и заводить второе
        # на ту же трату нельзя: списалось бы дважды. Своё правило «50 мл из
        # своей бутылки» важнее заготовки.
        #
        # Кроме одного случая: правило штучное, а позиция наливается. Так
        # заводили раньше, и это тихо неверно — бокал вина списывал целую
        # бутылку. Чиним, пока никто не посчитал остаток: тронуть полку,
        # которую уже пересчитали, куда хуже, чем оставить старое правило.
        if existing:
            if by_volume:
                for rule in (r for r in existing if not r.options):
                    if rule.by_volume:
                        continue
                    shelf = db.get(StockItem, rule.stock_item_id)
                    if shelf is None or Decimal(str(shelf.quantity)) != 0:
                        continue
                    shelf.unit = UNIT_ML
                    rule.by_volume = True
                    rule.per_unit = bottle_ml(item)
                    fixed += 1
            continue

        parts = list(item.ingredients or []) if item.category in MADE_HERE else []

        if by_volume:
            stock_item = line(item.name, UNIT_ML)
            db.add(
                Recipe(
                    venue_id=venue.id,
                    menu_item_id=item.id,
                    stock_item_id=stock_item.id,
                    options={},
                    per_unit=bottle_ml(item),
                    by_volume=True,
                )
            )
            made_rules += 1
            continue

        if parts:
            # У коктейля своя единица: жидкое считают миллилитрами, еду —
            # граммами. Ошибиться здесь не страшно, единицу правят в строке.
            unit = UNIT_ML if item.station == STATION_BAR else UNIT_G
            for part in parts:
                name = str(part.get("name") or part.get("key") or "").strip()
                if not name:
                    continue
                db.add(
                    Recipe(
                        venue_id=venue.id,
                        menu_item_id=item.id,
                        stock_item_id=line(name, unit).id,
                        options={},
                        # Ноль намеренно: сколько мяты в мохито, каталог не
                        # знает, а выдуманная цифра врёт убедительнее пустой.
                        per_unit=0,
                    )
                )
                made_rules += 1
                blank += 1
            continue

        db.add(
            Recipe(
                venue_id=venue.id,
                menu_item_id=item.id,
                stock_item_id=line(item.name, UNIT_PC).id,
                options={},
                per_unit=1,
            )
        )
        made_rules += 1

    db.commit()
    realtime.publish(realtime.CHANNEL_STOCK, {"type": "stock.changed"})
    return {"items": made_items, "recipes": made_rules, "blank": blank, "fixed": fixed}


@router.get("/inventory")
def inventory(
    month: str | None = Query(default=None, pattern=r"^\d{4}-\d{2}$"),
    actor: User = Depends(require("stock.view")),
    db: DbSession = Depends(get_db),
    venue: Venue = Depends(get_venue),
) -> dict:
    """Инвентаризация: сколько должно быть, сколько есть и куда делась разница.

    Текущий лист — это «должно быть» прямо сейчас: расчётный остаток против
    полки. Фактическое число вписывает человек, и записывается не оно, а
    разница: само число ничего не объясняет, объясняет расхождение.

    Прошлые пересчёты лежат по месяцам. Через полгода вопрос звучит не «что
    там сейчас», а «когда началось расхождение».
    """
    items = db.scalars(
        select(StockItem)
        .where(StockItem.venue_id == venue.id, StockItem.active.is_(True))
        .order_by(StockItem.name)
    ).all()

    counts = db.scalars(
        select(StockMove)
        .where(StockMove.venue_id == venue.id, StockMove.reason == MOVE_COUNT)
        .order_by(StockMove.at.desc())
    ).all()

    names = {u.id: u.name for u in db.scalars(select(User).where(User.venue_id == venue.id)).all()}
    titles = {i.id: i for i in items}

    months: dict[str, dict] = {}
    for row in counts:
        key = row.at.strftime("%Y-%m")
        item = titles.get(row.stock_item_id)
        bucket = months.setdefault(key, {"month": key, "rows": [], "gap": 0.0})
        bucket["rows"].append(
            {
                "at": row.at.isoformat(),
                "name": item.name if item else "—",
                "unit_name": UNIT_NAMES.get(item.unit, "") if item else "",
                # Разница и есть суть записи: минус — недостача, плюс — нашлось.
                "difference": float(row.delta),
                "who": names.get(row.by_id, "—"),
                "note": row.note,
            }
        )
        bucket["gap"] += float(row.delta)

    want = month or (sorted(months, reverse=True)[0] if months else None)
    return {
        "months": sorted(months, reverse=True),
        "month": want,
        "history": months.get(want, {"month": want, "rows": [], "gap": 0.0}),
        # Лист на сегодня: расчётный остаток, который надо сверить с полкой.
        "sheet": [
            {
                "id": str(i.id),
                "name": i.name,
                "unit_name": UNIT_NAMES.get(i.unit, i.unit),
                "expected": float(i.quantity),
            }
            for i in items
        ],
    }


class ItemIn(BaseModel):
    name: str = Field(min_length=1, max_length=160)
    unit: str = "pc"
    quantity: float = 0
    low_at: float = 0
    note: str | None = None


@router.post("", status_code=201)
def create(
    body: ItemIn,
    actor: User = Depends(require("stock.edit")),
    db: DbSession = Depends(get_db),
    venue: Venue = Depends(get_venue),
) -> dict:
    if body.unit not in UNITS:
        raise HTTPException(status_code=422, detail="неизвестная единица")
    twin = db.scalars(
        select(StockItem).where(StockItem.venue_id == venue.id, StockItem.name == body.name.strip())
    ).first()
    if twin is not None:
        raise HTTPException(status_code=409, detail="такая позиция уже есть")

    item = StockItem(
        venue_id=venue.id,
        name=body.name.strip(),
        unit=body.unit,
        low_at=Decimal(str(body.low_at)),
        note=(body.note or "").strip() or None,
        quantity=0,
    )
    db.add(item)
    db.flush()
    moves = []
    if body.quantity:
        # Стартовый остаток — это приход, а не «просто число»: иначе первая
        # же сверка не сойдётся и объяснить будет нечем.
        moves.append(
            stock.move(db, item, Decimal(str(body.quantity)), MOVE_IN, user=actor,
                       note="стартовый остаток")
        )
    db.commit()
    stock.announce(db, venue.id, moves)
    return stock.item_payload(item)


class ItemPatch(BaseModel):
    name: str | None = None
    unit: str | None = None
    low_at: float | None = None
    note: str | None = None
    active: bool | None = None


@router.patch("/{item_id}")
def edit(
    item_id: uuid.UUID,
    body: ItemPatch,
    actor: User = Depends(require("stock.edit")),
    db: DbSession = Depends(get_db),
    venue: Venue = Depends(get_venue),
) -> dict:
    item = _item(db, venue, item_id)
    cleared = 0
    if body.name is not None:
        item.name = body.name.strip()
    if body.unit is not None and body.unit != item.unit:
        # Единицу меняют, когда поняли, как это считают на самом деле: сок
        # приезжает пачками, а наливают его в стакан — значит миллилитры, а
        # не «штуки».
        #
        # Но только пока по позиции не было движений. «3» в штуках и «3» в
        # миллилитрах — это разные три, и переписать единицу под чужой цифрой
        # значит соврать в инвентаризации, не тронув ни одного числа.
        if body.unit not in UNITS:
            raise HTTPException(status_code=422, detail="Такой единицы нет")
        if item.id in stock.touched(db, venue.id):
            raise HTTPException(
                status_code=409,
                detail="По этой позиции уже считали остаток. "
                "Единицу можно поменять, только пока движений не было.",
            )
        item.unit = body.unit
        # Расход в правилах записан числом без единицы. Была штука — станет
        # миллилитр, и «1» из «одна банка» молча превратится в «один
        # миллилитр сока». Обнуляем: ноль виден в списке как «без расхода» и
        # ничего не списывает, а выдуманная цифра списывает неправильно и
        # молчит.
        cleared = 0
        for rule in db.scalars(
            select(Recipe).where(Recipe.stock_item_id == item.id)
        ).all():
            if rule.by_volume or float(rule.per_unit) == 0:
                continue
            rule.per_unit = 0
            cleared += 1
    if body.low_at is not None:
        item.low_at = Decimal(str(body.low_at))
    if body.note is not None:
        item.note = body.note.strip() or None
    if body.active is not None:
        item.active = body.active
    db.commit()
    # Порог мог поменяться — экран склада должен показать это сам.
    realtime.publish(realtime.CHANNEL_STOCK, {"type": "stock.changed"})
    return {**stock.item_payload(item), "cleared": cleared}


class MoveIn(BaseModel):
    delta: float | None = None
    # Инвентаризация присылает не разницу, а то, что насчитали на полке.
    counted: float | None = None
    reason: str = MOVE_IN
    note: str | None = None


@router.post("/{item_id}/move")
def register(
    item_id: uuid.UUID,
    body: MoveIn,
    actor: User = Depends(require("stock.edit")),
    db: DbSession = Depends(get_db),
    venue: Venue = Depends(get_venue),
) -> dict:
    """Приход, списание или пересчёт.

    Продажи сюда не приходят: их пишет сам зал, когда позиция уходит на
    станцию.
    """
    item = _item(db, venue, item_id)
    if body.reason not in MOVE_REASONS:
        raise HTTPException(status_code=422, detail="неизвестная причина")

    if body.counted is not None:
        row = stock.count_to(db, item, body.counted, actor, body.note)
    else:
        if not body.delta:
            raise HTTPException(status_code=422, detail="ноль двигать незачем")
        delta = abs(body.delta) if body.reason == MOVE_IN else body.delta
        if body.reason == MOVE_WRITE_OFF:
            delta = -abs(body.delta)
        row = stock.move(db, item, delta, body.reason, user=actor, note=body.note)

    record.write(
        db,
        venue_id=venue.id,
        user_id=actor.id,
        action="stock.move",
        entity=f"stock:{item.name}",
        after={"delta": float(row.delta), "reason": body.reason, "note": body.note},
    )
    db.commit()
    stock.announce(db, venue.id, [row])
    return stock.item_payload(item)


@router.get("/{item_id}/moves")
def moves(
    item_id: uuid.UUID,
    limit: int = Query(default=50, ge=1, le=200),
    actor: User = Depends(require("stock.view")),
    db: DbSession = Depends(get_db),
    venue: Venue = Depends(get_venue),
) -> list[dict]:
    item = _item(db, venue, item_id)
    rows = db.scalars(
        select(StockMove)
        .where(StockMove.stock_item_id == item.id)
        .order_by(StockMove.at.desc())
        .limit(limit)
    ).all()
    names = {u.id: u.name for u in db.scalars(select(User).where(User.venue_id == venue.id)).all()}
    return [
        {
            "at": m.at.isoformat(),
            "delta": float(m.delta),
            "reason": m.reason,
            "reason_name": MOVE_NAMES.get(m.reason, m.reason),
            # У продажи имя тоже есть: её записывает тот, кто отправил заказ.
            "who": names.get(m.by_id, "—"),
            "note": m.note,
        }
        for m in rows
    ]


# ------------------------------------------------------------- рецепты ----
class RecipeIn(BaseModel):
    menu_item_id: uuid.UUID
    stock_item_id: uuid.UUID
    per_unit: float = Field(gt=0)
    # {"size": "ml50"} — правило только для этого варианта; пусто — для любого.
    options: dict = Field(default_factory=dict)


def _variant_text(item: MenuItem | None, chosen: dict) -> str:
    """«Объём: 50 мл» вместо «size: ml50».

    Ключи нужны машине, человеку нужны названия — а правило списания читают
    глазами, сверяя с бутылкой на полке.
    """
    if not chosen:
        return ""
    groups = {g["key"]: g for g in ((item.options if item else None) or [])}
    parts = []
    for key, value in chosen.items():
        group = groups.get(key)
        if group is None:
            parts.append(f"{key}: {value}")
            continue
        choice = next((c for c in group["choices"] if c["key"] == value), None)
        parts.append(f"{group.get('label') or key}: {choice['name'] if choice else value}")
    return " · ".join(parts)


@router.get("/gaps")
def gaps(
    actor: User = Depends(require("stock.view")),
    db: DbSession = Depends(get_db),
    venue: Venue = Depends(get_venue),
) -> list[dict]:
    """Что можно выбрать в заказе, но со склада за это ничего не уходит.

    Микс называется в меню, официант его нажимает, гость его выпивает — а на
    полке всё по-прежнему. Это самая тихая дыра в учёте: она не ошибается и
    не жалуется, просто к концу месяца не сходится тоник.

    Смотрим только группы с вариантами-продуктами — миксы. Объём разбирается
    правилом самой позиции, а «дарк-лиф» ничем на полке и не является.
    """
    items = db.scalars(
        select(MenuItem).where(MenuItem.venue_id == venue.id, MenuItem.active.is_(True))
    ).all()
    rules: dict = {}
    for r in db.scalars(select(Recipe).where(Recipe.venue_id == venue.id)).all():
        rules.setdefault(r.menu_item_id, []).append(r)

    out = []
    for item in items:
        mine = rules.get(item.id, [])
        covered = {
            tuple(sorted((r.options or {}).items()))
            for r in mine
            if r.options and float(r.per_unit) > 0
        }
        for group in item.options or []:
            key = str(group.get("key") or "")
            if not key or key in SIZE_GROUPS:
                continue
            # Группа с одним выбором и без цены — это вкус, а не продукт:
            # марка табака, лист, чаша. Расход за них не ждут.
            if not any(
                c.get("add_pence") or c.get("price_pence") for c in group.get("choices") or []
            ):
                continue
            for choice in group.get("choices") or []:
                if ((key, str(choice.get("key"))),) in covered:
                    continue
                out.append(
                    {
                        "menu_item": item.name,
                        "menu_item_id": str(item.id),
                        "group": group.get("label") or key,
                        "group_key": key,
                        "choice": choice.get("name"),
                        "choice_key": choice.get("key"),
                    }
                )
    return out


@router.get("/recipes")
def recipes(
    actor: User = Depends(require("stock.view")),
    db: DbSession = Depends(get_db),
    venue: Venue = Depends(get_venue),
) -> list[dict]:
    rows = db.scalars(select(Recipe).where(Recipe.venue_id == venue.id)).all()
    menu = {
        i.id: i for i in db.scalars(select(MenuItem).where(MenuItem.venue_id == venue.id)).all()
    }
    goods = {
        i.id: i for i in db.scalars(select(StockItem).where(StockItem.venue_id == venue.id)).all()
    }
    return [
        {
            "id": str(r.id),
            "menu_item_id": str(r.menu_item_id),
            "menu_item": menu[r.menu_item_id].name if r.menu_item_id in menu else "—",
            "stock_item_id": str(r.stock_item_id),
            "stock_item": goods[r.stock_item_id].name if r.stock_item_id in goods else "—",
            "unit_name": UNIT_NAMES.get(goods[r.stock_item_id].unit, "")
            if r.stock_item_id in goods
            else "",
            "options": dict(r.options or {}),
            "options_text": _variant_text(menu.get(r.menu_item_id), dict(r.options or {})),
            "per_unit": float(r.per_unit),
        }
        for r in rows
    ]


class RecipePatch(BaseModel):
    per_unit: float = Field(ge=0)


@router.patch("/recipes/{recipe_id}")
def edit_recipe(
    recipe_id: uuid.UUID,
    body: RecipePatch,
    actor: User = Depends(require("stock.edit")),
    db: DbSession = Depends(get_db),
    venue: Venue = Depends(get_venue),
) -> dict:
    """Поправить расход в правиле.

    Заготовка ставит ноль там, где расход знает только человек: сколько мяты
    в мохито, каталог не знает. Вписывать это удалением и добавлением правила
    заново — тридцать лишних движений на одно меню.
    """
    row = db.get(Recipe, recipe_id)
    if row is None or row.venue_id != venue.id:
        raise HTTPException(status_code=404, detail="правило не найдено")
    row.per_unit = Decimal(str(body.per_unit))
    db.commit()
    realtime.publish(realtime.CHANNEL_STOCK, {"type": "stock.changed"})
    return {"status": "ok", "per_unit": float(row.per_unit)}


@router.post("/recipes", status_code=201)
def add_recipe(
    body: RecipeIn,
    actor: User = Depends(require("stock.edit")),
    db: DbSession = Depends(get_db),
    venue: Venue = Depends(get_venue),
) -> dict:
    menu_item = db.get(MenuItem, body.menu_item_id)
    if menu_item is None or menu_item.venue_id != venue.id:
        raise HTTPException(status_code=404, detail="позиции меню нет")
    goods = _item(db, venue, body.stock_item_id)

    row = Recipe(
        venue_id=venue.id,
        menu_item_id=menu_item.id,
        stock_item_id=goods.id,
        options=body.options or {},
        per_unit=Decimal(str(body.per_unit)),
    )
    db.add(row)
    db.commit()
    return {"id": str(row.id), "menu_item": menu_item.name, "stock_item": goods.name}


@router.delete("/recipes/{recipe_id}")
def drop_recipe(
    recipe_id: uuid.UUID,
    actor: User = Depends(require("stock.edit")),
    db: DbSession = Depends(get_db),
    venue: Venue = Depends(get_venue),
) -> dict:
    row = db.get(Recipe, recipe_id)
    if row is None or row.venue_id != venue.id:
        raise HTTPException(status_code=404, detail="правила нет")
    db.delete(row)
    db.commit()
    return {"status": "ok"}
