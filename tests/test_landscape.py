import json
import pytest
from citysim.landscape import (DATA_DIR, Landscape, Tables, condensed, default_tables, full_text, generate_landscape,
                               load_landscape, load_tables, save_landscape, tier_of, viable)

SEEDS = range(300)


def test_default_tables_load_and_cross_reference():
    t = default_tables()
    assert len(t.resources) >= 16 and len(t.climates) >= 9 and len(t.terrains) >= 8
    assert any(r.kind == "finite" for r in t.resources) and any(r.kind == "renewable" for r in t.resources)


def test_bad_table_entries_are_rejected_with_a_clear_message():
    raw = json.loads((DATA_DIR / "resources.json").read_text())
    env = json.loads((DATA_DIR / "environment.json").read_text())
    bad = json.loads(json.dumps(raw))
    bad["resources"][0]["climate_mult"] = {"no_such_climate": 2.0}
    with pytest.raises(ValueError, match="unknown climate"):
        Tables(resources=bad["resources"], **env)
    bad = json.loads(json.dumps(raw))
    bad["resources"][7].pop("reserve_years")                     # a finite resource without a reserve
    with pytest.raises(ValueError, match="reserve_years"):
        Tables(resources=bad["resources"], **env)
    bad = json.loads(json.dumps(raw))
    bad["resources"].append(dict(bad["resources"][0]))           # duplicate id
    with pytest.raises(ValueError, match="duplicate"):
        Tables(resources=bad["resources"], **env)


def test_same_seed_same_sheet_different_seed_different_sheet():
    a, b = generate_landscape("alpha"), generate_landscape("alpha")
    assert a == b and a.model_dump_json() == b.model_dump_json()
    assert generate_landscape(1) == generate_landscape("1")
    assert len({generate_landscape(s).model_dump_json() for s in range(20)}) > 15


def test_extending_a_table_does_not_change_the_draws_of_existing_entries():
    t = default_tables()
    raw = json.loads((DATA_DIR / "resources.json").read_text())
    env = json.loads((DATA_DIR / "environment.json").read_text())
    raw["resources"].append({"id": "amber", "name": "amber", "kind": "finite", "base": 0.5, "reserve_years": [50, 100]})
    bigger = Tables(resources=raw["resources"], **env)
    for s in range(30):
        a, b = generate_landscape(s, tables=t), generate_landscape(s, tables=bigger)
        assert (a.climate, a.terrain, a.water, a.hazards) == (b.climate, b.terrain, b.water, b.hazards)
        assert [d for d in b.resources if d.id != "amber"] == a.resources


def test_every_generated_site_can_feed_a_city_and_has_water():
    t = default_tables()
    for s in SEEDS:
        sheet = generate_landscape(s)
        assert viable(sheet, t) and sheet.water
        assert any(d.richness >= 0.25 for d in sheet.with_tag("food_source", t))


def test_deposits_follow_their_table_ranges_and_tiers():
    t = default_tables()
    for s in range(100):
        for d in generate_landscape(s).resources:
            r = t.resource(d.id)
            assert d.kind == r.kind and d.tier == tier_of(d.richness) and 0 <= d.richness <= 1
            if d.kind == "finite":
                assert r.reserve_years[0] <= d.reserve_years <= r.reserve_years[1] and d.regeneration_ratio is None
            else:
                assert r.regeneration_ratio[0] <= d.regeneration_ratio <= r.regeneration_ratio[1] and d.reserve_years is None


def test_resources_that_need_water_never_appear_without_it():
    for s in SEEDS:
        sheet = generate_landscape(s)
        if "sea_coast" not in sheet.water:
            assert not sheet.has("sea_fish")
        if not set(sheet.water) & {"river", "lake", "marsh", "oasis"}:
            assert not sheet.has("freshwater_fish")


def test_terrain_shapes_what_is_found():
    def rate(terrain, rid):
        return sum(generate_landscape(s, terrain=terrain).has(rid) for s in range(150)) / 150
    assert rate("mountain_foothills", "iron_ore") > 2 * rate("floodplain", "iron_ore")
    assert rate("floodplain", "fertile_soil") > rate("mountain_foothills", "fertile_soil")


def test_forced_settings_work_and_bad_ones_fail():
    sheet = generate_landscape(3, climate="hot_desert", terrain="floodplain")
    assert (sheet.climate, sheet.terrain) == ("hot_desert", "floodplain")
    with pytest.raises(ValueError, match="unknown climate"):
        generate_landscape(3, climate="atlantis")


def test_condensed_layer_has_fixed_order_and_respects_the_cap():
    t = default_tables()
    for s in range(60):
        sheet = generate_landscape(s)
        text = condensed(sheet, t)
        assert len(text) <= 600
        assert text.index("Climate:") < text.index("Renewable:") < text.index("Finite:")
        loose = condensed(sheet, t, max_chars=10_000)
        assert "Absent:" in loose or len(sheet.resources) == len(t.resources)
    tiny = condensed(generate_landscape(2), t, max_chars=120)
    assert len(tiny) <= 120


def test_save_and_load_round_trip(tmp_path):
    sheet = generate_landscape("rt", name="Testville")
    files = save_landscape(sheet, tmp_path)
    assert all(f.exists() for f in files)
    assert load_landscape(tmp_path) == sheet
    assert "Testville" in (tmp_path / "landscape.md").read_text()
    assert (tmp_path / "landscape_condensed.txt").read_text() == condensed(sheet)
    sheet.description = "A windy place."
    assert "A windy place." in full_text(sheet)


def test_queries_for_later_stages():
    t = default_tables()
    sheet = generate_landscape(1)
    assert all(d.kind == "finite" for d in sheet.finite())
    assert {d.id for d in sheet.with_tag("food_source", t)} <= {d.id for d in sheet.resources}
    assert sheet.has("fertile_soil") and not sheet.has("tin_ore")
