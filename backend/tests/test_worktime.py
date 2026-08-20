"""Табель: сколько человек отработал.

Отчёт по смене отвечает «сколько заведение заработало». Здесь другое — «сколько
отработал вот этот человек», и путать эти два ответа нельзя: зарплату платят за
часы.
"""

from datetime import timedelta

from sqlalchemy import select

from app.models import WorkShift, utcnow
from app.services import worktime
from tests.test_floor import add, hall, login, open_check  # noqa: F401


def shift_row(db, name="Аня"):
    return db.scalars(
        select(WorkShift).where(WorkShift.name_snapshot == name)
    ).first()


def test_shift_starts_counting_time(client, hall, db):
    login(client, "1111")
    assert client.get("/api/work/shift").json() == {"open": False}

    opened = client.post("/api/work/shift/open").json()
    assert opened["open"] is True
    assert opened["minutes"] == 0

    # Время идёт от открытия, а не от закрытия приложения.
    row = shift_row(db)
    row.opened_at = utcnow() - timedelta(hours=7, minutes=20)
    db.commit()

    now = client.get("/api/work/shift").json()
    assert now["minutes"] == 440
    assert now["hours_text"] == "7 ч 20 мин"


def test_second_open_does_not_start_a_second_shift(client, hall, db):
    """Иначе за один вечер получается два табеля."""
    login(client, "1111")
    first = client.post("/api/work/shift/open").json()
    again = client.post("/api/work/shift/open").json()
    assert first["id"] == again["id"]


def test_closing_counts_hours_and_shows_the_evening(client, hall, db):
    login(client, "1111")
    client.post("/api/work/shift/open")
    row = shift_row(db)
    row.opened_at = utcnow() - timedelta(hours=6)
    db.commit()

    check = open_check(client, hall, guests=2)
    add(client, check["id"], hall["mojito"], qty=2)          # £32.00
    check = client.post(f"/api/checks/{check['id']}/send").json()
    client.post(
        f"/api/checks/{check['id']}/close",
        json={"payments": [{"method": "card", "amount_pence": check["due_pence"]}]},
    )

    closed = client.post("/api/work/shift/close").json()
    assert closed["open"] is False
    assert closed["minutes"] == 360
    assert closed["hours_text"] == "6 ч"

    # Итог вечера складывается снимком: через полгода пересчитать его не по чему.
    report = closed["report"]
    assert report["checks"] == 1
    assert report["guests"] == 2
    assert report["revenue_pence"] == 3200
    assert report["card_pence"] == 3200
    assert report["cash_pence"] == 0
    assert report["auto_closed"] is False


def test_open_check_keeps_the_shift_open(client, hall, db):
    """Уйти домой с открытым чеком — оставить деньги на столе."""
    login(client, "1111")
    client.post("/api/work/shift/open")
    check = open_check(client, hall)
    add(client, check["id"], hall["mojito"])
    client.post(f"/api/checks/{check['id']}/send")

    r = client.post("/api/work/shift/close")
    assert r.status_code == 409
    assert "чек" in r.json()["detail"].lower()
    assert client.get("/api/work/shift").json()["open"] is True

    client.post(
        f"/api/checks/{check['id']}/close",
        json={"payments": [{"method": "cash", "amount_pence": 1600}]},
    )
    assert client.post("/api/work/shift/close").json()["open"] is False


def test_forgotten_shift_closes_itself(client, hall, db):
    """Телефон унесли домой — в табеле не должно вырасти четырнадцать часов сна."""
    login(client, "1111")
    client.post("/api/work/shift/open")
    row = shift_row(db)
    row.opened_at = utcnow() - timedelta(hours=30)
    db.commit()

    assert client.get("/api/work/shift").json() == {"open": False}
    db.expire_all()
    row = shift_row(db)
    assert row.closed_at is not None
    assert row.minutes == worktime.MAX_HOURS * 60
    assert row.report["auto_closed"] is True


def test_timesheet_adds_up_the_hours(client, hall, db):
    login(client, "1111")
    client.post("/api/work/shift/open")
    row = shift_row(db)
    row.opened_at = utcnow() - timedelta(hours=5)
    db.commit()
    client.post("/api/work/shift/close")

    login(client, "444444")   # менеджер: табель это деньги
    body = client.get("/api/admin/timesheet").json()
    anya = next(p for p in body["people"] if p["name"] == "Аня")
    assert anya["shifts"] == 1
    assert anya["minutes"] == 300
    assert anya["hours_text"] == "5 ч"
    assert body["shifts"][0]["name"] == "Аня"


def test_timesheet_is_not_for_everyone(client, hall):
    """По табелю считают зарплату — это не общий экран."""
    login(client, "1111")
    assert client.get("/api/admin/timesheet").status_code == 403


def test_kept_for_a_year_and_no_longer(client, hall, db, venue, make_user):
    """Год — и хватит: дальше это не табель, а склад мусора."""
    login(client, "1111")
    user = client.get("/api/auth/me").json()
    old = WorkShift(
        venue_id=venue.id,
        user_id=user["id"],
        name_snapshot="Аня",
        role_snapshot="waiter",
        opened_at=utcnow() - timedelta(days=400),
        closed_at=utcnow() - timedelta(days=400) + timedelta(hours=6),
        minutes=360,
        report={},
    )
    keep = WorkShift(
        venue_id=venue.id,
        user_id=user["id"],
        name_snapshot="Аня",
        role_snapshot="waiter",
        opened_at=utcnow() - timedelta(days=300),
        closed_at=utcnow() - timedelta(days=300) + timedelta(hours=6),
        minutes=360,
        report={},
    )
    db.add_all([old, keep])
    db.commit()

    client.post("/api/work/shift/open")
    client.post("/api/work/shift/close")

    left = db.scalars(select(WorkShift)).all()
    ages = sorted((utcnow() - r.opened_at).days for r in left)
    assert 400 not in ages
    assert 300 in ages
