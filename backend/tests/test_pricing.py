import pytest
from sqlalchemy import select

from app.models import MenuItem
from app.services.pricing import PriceError, resolve


def item(db, key: str) -> MenuItem:
    return db.scalars(select(MenuItem).where(MenuItem.key == key)).one()


def test_size_replaces_price(db, venue):
    vodka = item(db, "vodka-house")
    price, names, _ = resolve(vodka, {"size": "bottle", "kind": "absolut"})
    assert price == 23000
    assert names == ["Бутылка", "Absolut"]


def test_required_group_cannot_be_skipped(db, venue):
    """«Мохито» без вкуса — это не заказ, а загадка для бармена."""
    vodka = item(db, "vodka-house")
    with pytest.raises(PriceError) as exc:
        resolve(vodka, {"size": "ml50"})
    assert exc.value.payload["missing_option"] == "kind"


def test_mixer_names_the_drink(db, venue):
    """«Микс» без названия напитка — загадка для бармена ровно так же,
    как «Мохито» без вкуса."""
    vodka = item(db, "vodka-house")
    mixer = next(g for g in vodka.options if g["key"] == "mixer")
    names = [c["name"] for c in mixer["choices"]]
    assert "Cola" in names and "Апельсиновый сок" in names
    # Горячее в стакан с виски не льют, а пиво миксом не бывает.
    assert "Corona" not in names
    assert all("чай" not in n.lower() and "кофе" not in n.lower() for n in names)


def test_addon_adds_and_counts(db, venue):
    vodka = item(db, "vodka-house")
    price, names, chosen = resolve(
        vodka,
        {"size": "ml50", "kind": "stoli", "mixer": ["soft-drink:cola", "soft-drink:cola"]},
    )
    assert price == 1300 + 300 * 2
    # На марке видно, что это разбавить, а не отдельный стакан колы.
    assert "Микс: Cola ×2" in names
    assert chosen["mixer"] == ["soft-drink:cola", "soft-drink:cola"]


def test_two_different_mixers(db, venue):
    """Кола к одному стакану, сок к другому — это одна строка чека."""
    vodka = item(db, "vodka-house")
    price, names, _ = resolve(
        vodka,
        {"size": "ml100", "kind": "absolut", "mixer": ["soft-drink:cola", "soft-drink:orange"]},
    )
    assert price == 2600 + 300 * 2
    assert "Микс: Cola" in names
    assert "Микс: Апельсиновый сок" in names


def test_addon_respects_limit(db, venue):
    vodka = item(db, "vodka-house")
    with pytest.raises(PriceError):
        resolve(vodka, {"size": "ml50", "kind": "stoli", "mixer": ["soft-drink:cola"] * 7})


def test_unknown_mixer_is_rejected(db, venue):
    """Браузер присылает, что выбрали, а не что придумали."""
    vodka = item(db, "vodka-house")
    with pytest.raises(PriceError):
        resolve(vodka, {"size": "ml50", "kind": "stoli", "mixer": ["soft-drink:whisky"]})


def test_dependent_group_required_only_when_relevant(db, venue):
    """Марку дарк-лифа не спрашивают у того, кто взял сигарный лист."""
    hookah = item(db, "hookah")
    price, names, chosen = resolve(hookah, {"leaf": "cigar-leaf", "cigar-leaf": "kraken"})
    assert price == 5000
    assert names == ["Сигарный лист", "Kraken"]
    assert "dark-leaf" not in chosen

    with pytest.raises(PriceError):
        resolve(hookah, {"leaf": "dark-leaf"})


def test_group_add_pence_applies_once(db, venue):
    hookah = item(db, "hookah")
    price, names, _ = resolve(
        hookah, {"leaf": "dark-leaf", "dark-leaf": "darkside", "fruit-head": "apple"}
    )
    assert price == 5000 + 1000
    assert "Яблоко" in names


def test_stale_choice_from_hidden_group_is_dropped(db, venue):
    """Выбор из выключённой группы не должен попасть в цену."""
    hookah = item(db, "hookah")
    price, _, chosen = resolve(
        hookah,
        {"leaf": "cigar-leaf", "cigar-leaf": "satyr", "dark-leaf": "tangiers"},
    )
    assert price == 5000
    assert "dark-leaf" not in chosen


def test_unknown_group_is_rejected(db, venue):
    with pytest.raises(PriceError):
        resolve(item(db, "mojito"), {"nonsense": "x"})


# ------------------------------------------- два микса к бутылке в цене ----
def test_two_mixers_come_with_the_bottle(db, venue):
    """К бутылке два микса в цене — правило заведения, а не подарок официанта."""
    vodka = item(db, "vodka-house")
    unit, names, _ = resolve(
        vodka,
        {"size": "bottle", "kind": "absolut",
         "mixer": ["soft-drink:cola", "soft-drink:sprite"]},
    )
    assert unit == 23000          # бутылка, миксы не добавили ничего
    assert any("Cola" in n for n in names)


def test_the_third_mixer_is_paid(db, venue):
    vodka = item(db, "vodka-house")
    unit, _, _ = resolve(
        vodka,
        {"size": "bottle", "kind": "absolut",
         "mixer": ["soft-drink:cola", "soft-drink:sprite", "soft-drink:fanta"]},
    )
    assert unit == 23000 + 300


def test_mixer_to_a_glass_is_paid_as_before(db, venue):
    """Бесплатные — только к бутылке: к стакану микс как был платным, так и остался."""
    vodka = item(db, "vodka-house")
    unit, _, _ = resolve(
        vodka, {"size": "ml50", "kind": "absolut", "mixer": ["soft-drink:cola"]}
    )
    assert unit == 1300 + 300
