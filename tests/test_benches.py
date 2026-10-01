"""Bench size keywords and fit checks."""
import pytest

from swhull.benches import SIZES, fits, overflow, parse_bench
from swhull.build import build, resolve_spec, summary


def test_sizes_are_nested():
    sizes = list(SIZES.values())
    for small, big in zip(sizes, sizes[1:]):
        assert all(s <= b for s, b in zip(small, big)), (small, big)


def test_starter_reach_matches_measurement():
    # measured in game: the starter bench reaches about +-13 x +-13 x +-28 blocks
    assert fits(SIZES["S"], (-13, -13, -28), (13, 13, 28))
    assert not fits(SIZES["S"], (-13, -13, -29), (13, 13, 28))


def test_overflow_in_metres():
    assert overflow(SIZES["S"], (-13, -13, -32), (13, 13, 32)) == (0, 0, 1.0)


@pytest.mark.parametrize("value", ["l", " MAX ", [10, 5, 30]])
def test_parse(value):
    assert parse_bench(value)


@pytest.mark.parametrize("value", ["huge", [1, 2], [0, 1, 1], "S M"])
def test_parse_rejects(value):
    with pytest.raises(ValueError):
        resolve_spec({"bench": value})


def test_summary_prompts_without_bench_and_checks_with_one():
    spec = resolve_spec(preset="tugboat")
    placed, info = build(spec)
    assert "Ask the player which bench size" in summary(spec, placed, info)
    spec = resolve_spec({"bench": "S"}, preset="tugboat")
    placed, info = build(spec)
    text = summary(spec, placed, info)
    assert "Does NOT fit bench S" in text and "too tall" in text
    assert "Fits bench sizes: M, L, XL, XXL, MAX" in text


def test_long_hulls_allowed_up_to_max():
    resolve_spec({"length": 120})
    with pytest.raises(ValueError):
        resolve_spec({"length": 121})
