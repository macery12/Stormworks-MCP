"""Show which body each part belongs to, like the game's bodies view.

The main body is grey; the others take distinct colours in order of their IDs, so previews of
the same vehicle (and of a subset of its bodies) match, and new bodies, which get higher IDs,
never repaint old ones.
"""
import copy

from .diagnostic_view import display

PALETTE = ("8A9299", "E6194B", "3CB44B", "4363D8", "F58231", "911EB4", "46C8F0", "F032E6", "BCF60C",
           "008080", "9A6324", "FFE119", "800000", "AAFFC3", "808000", "000075", "FABEBE", "E6BEFF",
           "FFD8B1", "5A5A5A")


def main_body(parts):
    return (parts[0].body if parts else "") or "1"


def colours(parts):
    """Body -> colour for a whole vehicle."""
    main = main_body(parts)
    others = sorted((b for b in counts(parts) if b != main), key=_order)
    return {main: PALETTE[0], **{b: PALETTE[1 + i % (len(PALETTE) - 1)] for i, b in enumerate(others)}}


def counts(parts):
    main, out = main_body(parts), {}
    for p in parts:
        out[p.body or main] = out.get(p.body or main, 0) + 1
    return out


def only(parts, bodies):
    """Parts of the listed bodies; every listed body must exist."""
    if not bodies:
        return parts
    main = main_body(parts)
    present = set(counts(parts))
    missing = [str(b) for b in bodies if str(b) not in present]
    if missing:
        raise ValueError(f"no body {missing[0]!r}; bodies are {', '.join(sorted(present, key=_order))}")
    wanted = {str(b) for b in bodies}
    return [p for p in parts if (p.body or main) in wanted]


def recolour(parts, vehicle=None):
    """Copies painted one colour per body; `vehicle` (all parts) fixes the colours when `parts`
    is a subset."""
    vehicle = vehicle or parts
    main, palette = main_body(vehicle), colours(vehicle)
    out = []
    for p in parts:
        q = copy.copy(p)
        q.faces = ()
        q.color = palette[p.body or main]
        out.append(q)
    return out


def labels(parts, main=None):
    """A "body N" label at each body's centre, in display coordinates."""
    main = main or main_body(parts)
    cells = {}
    for p in parts:
        cells.setdefault(p.body or main, []).extend(p.voxels())
    return [(display(tuple(sum(v[i] for v in vs) / len(vs) for i in range(3))), f"body {b}")
            for b, vs in sorted(cells.items(), key=lambda kv: _order(kv[0]))]


def legend(parts, vehicle=None):
    vehicle = vehicle or parts
    main, palette = main_body(vehicle), colours(vehicle)
    rows = sorted(counts(parts).items(), key=lambda kv: _order(kv[0]))
    return "Bodies (colour, parts): " + "; ".join(
        f"{b}{' (main)' if b == main else ''} #{palette[b]} {n}" for b, n in rows)


def _order(body):
    return (not body.isdigit(), int(body) if body.isdigit() else 0, body)
