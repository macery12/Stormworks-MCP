"""Shared materialisation for procedural designs and losslessly imported drafts."""
import copy

from .build import build, summary
from .editing import VehicleDocument, apply_edits, identify
from .pieces import add
from .vehicle import SPAWN_LIMIT, to_xml


def materialize(record, centred=False):
    from .routing import apply_routes  # noqa: PLC0415
    if record.get("kind") == "imported":
        document = VehicleDocument.parse(record["source_xml"])
        return apply_routes(record, apply_edits(document.parts, record.get("edits", []))), None
    if record.get("kind") == "land":
        from .land_presets import build_land  # noqa: PLC0415
        from .vehicle import centre  # noqa: PLC0415
        # Pre-preset land records are bare chassis; preserve their geometry and IDs.
        parts = build_land({"preset": "chassis", **record["spec"]})
        identify(parts)
        parts = apply_routes(record, parts)
        return (centre(parts) if centred else parts), None
    parts, info = build(record["spec"])
    if not centred:
        for p in parts:
            p.origin = add(p.origin, info["shift"])
        info["shift"] = (0, 0, 0)
    return apply_routes(record, identify(parts), info), info


def edited(record, operations):
    if not isinstance(operations, list) or not operations:
        raise ValueError("operations must be a nonempty list")
    out = copy.deepcopy(record)
    out.pop("history", None)
    target = out if out.get("kind") == "imported" else out["spec"]
    target.setdefault("edits", []).extend(copy.deepcopy(operations))
    return out


def describe(record, parts, info):
    if record.get("kind") == "land":
        from .land_build import summary as land_summary  # noqa: PLC0415
        return land_summary(record["spec"], parts)
    if info is not None:
        return summary(record["spec"], parts, info)
    cells = [v for p in parts for v in p.voxels()]
    size = [(max(v[i] for v in cells) - min(v[i] for v in cells) + 1) / 4 for i in range(3)]
    return (f"Imported draft: {len(parts)} parts; {size[2]:.2f} m long x {size[0]:.2f} m wide x "
            f"{size[1]:.2f} m tall. Original coordinates, settings and connections preserved.\n"
            f"Parts vs observed spawn limit: {len(parts)} of {SPAWN_LIMIT}."
            + ("\n! Exceeds the observed spawn limit." if len(parts) > SPAWN_LIMIT else ""))


def export(record):
    parts, info = materialize(record, centred=True)
    from .tanks import ensure_valid  # noqa: PLC0415
    ensure_valid(info)
    if record.get("kind") == "imported":
        xml = VehicleDocument.parse(record["source_xml"]).to_xml(parts)
    else:
        xml = to_xml(parts)
    from .networks import write_xml  # noqa: PLC0415
    xml = write_xml(xml, record, parts)
    return xml, len(parts), describe(record, parts, info)
