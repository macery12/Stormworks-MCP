"""Interior layout on the presets that ship with one."""
import pytest

from swhull import definitions
from swhull.build import build, resolve_spec


@pytest.mark.parametrize("preset", ["patrol_boat", "tugboat"])
def test_rooms_get_their_doors(preset):
    spec = resolve_spec(preset=preset)
    _, info = build(spec)
    plan = info["interior"]
    by_name = {r.name: r for r in plan.rooms}
    for room in spec["interior"]["rooms"]:
        built = by_name[room["name"]]
        assert built.air, f"{room['name']} has no space"
        sides = [d.split(" ")[0] for d in built.doors]
        assert sides == room.get("doors", []), f"{room['name']}: {built.doors}"
    assert not [w for w in plan.warnings if "door" in w]


def test_exterior_doors_only_above_main_deck():
    spec = resolve_spec(preset="patrol_boat")
    _, info = build(spec)
    main_deck = round(spec["depth"] * 4)          # first layer above the hull at midship
    for room in info["interior"].rooms:
        if any("exterior" in d for d in room.doors):
            assert room.ylo >= main_deck


@pytest.mark.skipif(definitions.definitions_dir() is None, reason="Stormworks not installed")
def test_placeholder_engine_fits():
    placed, info = build(resolve_spec(preset="patrol_boat"))
    assert any(p.piece.d == "engine_diesel" for p in placed)
    assert not [w for w in info["interior"].warnings if "engine" in w]
