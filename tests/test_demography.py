import pytest
from citysim.demography import Demography


def test_brief_example_100_pops():
    d = Demography(birth_rate_year=0, death_rate_year=0)
    figures, deaths = [], []
    for food in (99, 98, 96):
        r = d.step(100, food)
        figures.append(r.starving); deaths.append(r.starvation_deaths)
    assert figures == [1, 2, 4]
    assert deaths == [0, 0, 1]
    assert d.history == [0, 1, 3]            # the dead pop is not counted again


def test_deaths_not_counted_twice_on_following_month():
    d = Demography(0, 0)
    pop = 100.0
    for food in (99, 98, 96, 96):
        r = d.step(pop, food)
        pop = r.new_population
    assert r.starving == 3 and r.starvation_deaths == 1 and pop == 98


def test_record_resets_when_food_covers_population():
    d = Demography(0, 0)
    d.step(100, 99); d.step(100, 98)
    d.step(100, 100)                          # food >= population
    assert d.history == []
    r = d.step(100, 90)
    assert r.starvation_deaths == 0 and d.history == [10]


def test_partial_recovery_limits_deaths_to_persistently_starving():
    d = Demography(0, 0)
    d.step(100, 80); d.step(100, 90)          # 20, 10
    r = d.step(100, 95)                       # 5 -> min(20, 10, 5) = 5
    assert r.starvation_deaths == 5


def test_natural_rates_use_opening_population():
    d = Demography()
    r = d.step(12000, 12000)
    assert r.births == pytest.approx(12000 * 0.01 / 12)
    assert r.natural_deaths == pytest.approx(12000 * 0.0015 / 12)
    assert r.new_population == pytest.approx(12000 + r.births - r.natural_deaths)
    assert r.starvation_deaths == 0


def test_starvation_does_not_enter_natural_death_rate():
    d = Demography()
    r = d.step(1000, 500)
    assert r.natural_deaths == pytest.approx(1000 * 0.0015 / 12)


def test_extinction_below_one_pop():
    d = Demography(0, 0)
    r = d.step(0.5, 0)
    assert r.extinct and r.new_population == 0
