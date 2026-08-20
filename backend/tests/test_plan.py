"""Расстановка столов: план зала заводит управляющий, официант по нему работает."""

from sqlalchemy import select

from app.models import Table
from tests.test_floor import add, hall, login, open_check  # noqa: F401


def tables(client):
    return client.get("/api/admin/tables").json()


def test_seeded_tables_already_stand_somewhere(client, db, venue, hall):
    """План не открывается пустым: ровные ряды — заготовка, которую растащат."""
    login(client, "123456")
    rows = tables(client)
    assert all(t["x"] is not None and t["y"] is not None for t in rows)
    assert len({(t["x"], t["y"]) for t in rows}) == len(rows)


def test_plan_is_saved_in_one_request(client, db, venue, hall):
    """Пока стол тащат пальцем, он меняет место сто раз. Сто запросов по
    дороге — это сто шансов оставить план наполовину сохранённым."""
    login(client, "123456")
    rows = tables(client)
    moved = [
        {"id": rows[0]["id"], "x": 10.0, "y": 80.0},
        {"id": rows[1]["id"], "x": 90.0, "y": 20.0},
    ]
    assert client.post("/api/admin/tables/plan", json={"tables": moved}).status_code == 200

    after = {t["id"]: t for t in tables(client)}
    assert (after[rows[0]["id"]]["x"], after[rows[0]["id"]]["y"]) == (10.0, 80.0)
    assert (after[rows[1]["id"]]["x"], after[rows[1]["id"]]["y"]) == (90.0, 20.0)


def test_waiter_sees_the_same_plan(client, db, venue, hall):
    login(client, "123456")
    first = tables(client)[0]
    client.post(
        "/api/admin/tables/plan",
        json={"tables": [{"id": first["id"], "x": 33.0, "y": 66.0}]},
    )

    login(client, "1111")
    mine = next(t for t in client.get("/api/tables").json() if t["id"] == first["id"])
    assert (mine["x"], mine["y"]) == (33.0, 66.0)


def test_table_number_can_be_changed(client, db, venue, hall):
    login(client, "123456")
    first = tables(client)[0]
    body = client.patch(f"/api/admin/tables/{first['id']}", json={"label": "VIP"}).json()
    assert body["label"] == "VIP"

    login(client, "1111")
    assert any(t["label"] == "VIP" for t in client.get("/api/tables").json())


def test_two_tables_cannot_share_a_number(client, db, venue, hall):
    """Иначе официант несёт заказ не туда, и оба стола правы."""
    login(client, "123456")
    rows = tables(client)
    r = client.patch(f"/api/admin/tables/{rows[0]['id']}", json={"label": rows[1]["label"]})
    assert r.status_code == 409


def test_new_table_lands_where_asked(client, db, venue, hall):
    login(client, "123456")
    made = client.post(
        "/api/admin/tables",
        json={"label": "51", "zone": "Терраса", "seats": 2, "x": 20.0, "y": 40.0},
    ).json()
    assert (made["x"], made["y"]) == (20.0, 40.0)
    assert made["zone"] == "Терраса"


def test_unused_table_can_be_removed(client, db, venue, hall):
    login(client, "123456")
    made = client.post("/api/admin/tables", json={"label": "77"}).json()
    assert client.delete(f"/api/admin/tables/{made['id']}").status_code == 200
    assert all(t["label"] != "77" for t in tables(client))


def test_table_with_history_is_switched_off_not_deleted(client, db, venue, hall):
    """Закрытый чек должен знать, где сидели."""
    login(client, "1111")
    check = open_check(client, hall)
    add(client, check["id"], hall["mojito"])
    client.post(f"/api/checks/{check['id']}/send")
    client.post(
        f"/api/checks/{check['id']}/close",
        json={"payments": [{"method": "cash", "amount_pence": 1600}]},
    )

    login(client, "123456")
    used = next(t for t in tables(client) if t["id"] == hall["table"])
    assert used["ever_used"] is True
    assert client.delete(f"/api/admin/tables/{used['id']}").status_code == 409

    assert client.patch(f"/api/admin/tables/{used['id']}", json={"active": False}).status_code == 200
    login(client, "1111")
    assert all(t["id"] != hall["table"] for t in client.get("/api/tables").json())


def test_moving_a_table_between_zones(client, db, venue, hall):
    login(client, "123456")
    first = tables(client)[0]
    client.post(
        "/api/admin/tables/plan",
        json={"tables": [{"id": first["id"], "x": 50.0, "y": 50.0, "zone": "Терраса"}]},
    )
    after = next(t for t in tables(client) if t["id"] == first["id"])
    assert after["zone"] == "Терраса"


def test_waiter_cannot_rearrange_the_hall(client, db, venue, hall):
    """Стол, случайно сдвинутый на бегу, — это чужая расстановка на весь вечер."""
    login(client, "1111")
    rows = client.get("/api/tables").json()
    r = client.post(
        "/api/admin/tables/plan",
        json={"tables": [{"id": rows[0]["id"], "x": 1.0, "y": 1.0}]},
    )
    assert r.status_code == 403


# --------------------------------------------------- зал ставят целиком ---
def test_several_tables_at_once(client, db, venue, hall):
    """Двадцать столов по одному — это двадцать одинаковых форм подряд."""
    login(client, "123456")
    was = len(tables(client))
    r = client.post(
        "/api/admin/tables/batch",
        json={"count": 5, "zone": "Терраса", "seats": 2},
    )
    assert r.status_code == 201, r.text
    made = r.json()["tables"]
    assert len(made) == 5
    assert {t["zone"] for t in made} == {"Терраса"}
    assert {t["seats"] for t in made} == {2}
    assert len(tables(client)) == was + 5

    # Нумерация продолжается с последнего, а не начинается заново.
    numbers = sorted(int(t["label"]) for t in made)
    assert numbers == list(range(numbers[0], numbers[0] + 5))


def test_busy_numbers_are_skipped(client, db, venue, hall):
    """Упереться в «стол 7 уже есть» на середине списка хуже, чем пропуск."""
    login(client, "123456")
    client.post("/api/admin/tables", json={"label": "101", "zone": "Зал"})
    made = client.post(
        "/api/admin/tables/batch", json={"count": 3, "start": 100, "zone": "Зал"}
    ).json()["tables"]
    assert [t["label"] for t in made] == ["100", "102", "103"]


def test_batch_is_not_for_the_waiter(client, db, venue, hall):
    login(client, "1111")
    assert client.post("/api/admin/tables/batch", json={"count": 2}).status_code == 403


def test_unused_table_can_be_removed_after_it_was_switched_off(client, db, venue, hall):
    """Выключенный стол, по которому не было чеков, ни на что не ссылается."""
    login(client, "123456")
    made = client.post("/api/admin/tables", json={"label": "777", "zone": "Зал"}).json()
    client.patch(f"/api/admin/tables/{made['id']}", json={"active": False})
    off = next(t for t in tables(client) if t["id"] == made["id"])
    assert off["ever_used"] is False
    assert client.delete(f"/api/admin/tables/{made['id']}").status_code == 200
    assert all(t["id"] != made["id"] for t in tables(client))
