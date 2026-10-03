"""Opening the roof must clear the cockpit without detaching its fixtures."""
import pytest

from swhull.build import build, resolve_spec
from swhull.pieces import add


@pytest.mark.parametrize("mode", ["blocks", "wedges", "wedges_v2"])
def test_open_deck_cabin_has_supports_to_floor_and_remains_attached(mode):
    spec = resolve_spec({"length": 8, "beam": 4, "depth": 2, "deck": "open",
                         "smoothing": mode, "sheer": {"bow": 1, "stern": 0},
                         "interior": {"decks": [1.5]},
                         "superstructure": [{"name": "cabin", "z": 2, "length": 2,
                                             "width": 2, "y": 1.75, "height": 2}]})
    parts, info = build(spec)
    assert not any(w.startswith("loose part") for w in info["warnings"])
    assert any("support blocks" in w for w in info["interior"].warnings)
    owned = {add(v, info["shift"]): p for p in parts for v in p.voxels()}
    # Supports belong under the cabin perimeter, not across the centre of the cockpit.
    for z in range(4, 8):
        for y in range(6, 9):
            assert (0, y, z) not in owned


def test_supports_stay_within_hull_volume():
    _, info = build(resolve_spec({"length": 8, "beam": 4, "depth": 2, "deck": "open",
                                 "interior": {"decks": [1.5]},
                                 "superstructure": [{"name": "fixture", "z": 4, "length": 0.5,
                                                     "width": 0.5, "height": 0.5}]}))
    for v in info["interior"].blocks:
        assert v in info["region"]
