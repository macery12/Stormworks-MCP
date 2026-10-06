"""Guard the player's reversed default gear and deprecated-part regression."""
import copy

import pytest

from swhull import definitions
from swhull.configuration import gearbox_ratios
from swhull.connections import transmission_ports
from swhull.editing import VehicleDocument, part
from swhull.land import catalogue
from swhull.networks import physical_graph, preflight
from swhull.part_policy import CURRENT_GEARBOXES, GEARBOXES, LEGACY_GEARBOXES, allowed
from swhull.pieces import ROTATIONS, Placed, add, apply, r_attr
from swhull.vehicle import to_xml
from swhull.reference import xml_root


@pytest.fixture
def gearboxes(tmp_path, monkeypatch):
    # Invented one-cell fixtures with opposite shaft faces, not copied game assets.
    for d in GEARBOXES | {"modular_engine_cylinder", "engine"}:
        (tmp_path / f"{d}.xml").write_text(
            f'<definition name="{d}"><voxels><voxel flags="1"><position/></voxel></voxels>'
            '<surfaces><surface orientation="2" trans_type="1"><position/></surface>'
            '<surface orientation="3" trans_type="1"><position/></surface></surfaces></definition>')
    monkeypatch.setattr(definitions, "definitions_dir", lambda: str(tmp_path))
    definitions.load.cache_clear()
    definitions.metadata.cache_clear()
    yield
    definitions.load.cache_clear()
    definitions.metadata.cache_clear()


@pytest.mark.parametrize("d", sorted(CURRENT_GEARBOXES))
@pytest.mark.parametrize("q", ROTATIONS)
def test_new_current_gearboxes_export_forward_off_reverse_on_in_every_rotation(gearboxes, d, q):
    for p in (Placed(definitions.load(d), (0, 0, 0), q),
              part({"definition": d, "position": [0, 0, 0], "rotation": q})):
        xml = to_xml([p])
        o = xml_root(xml).find("bodies/body/components/c/o")
        assert (o.get("gear_ratio_1"), o.get("gear_ratio_2")) == ("1", "0")
        assert o.get("r") == r_attr(q)
        row = gearbox_ratios(p)
        assert row["off"]["direction"] == "forward" and row["on"]["direction"] == "reverse"
        faces = transmission_ports(p)
        assert {f["normal"] for f in faces} == {apply(q, (0, 1, 0)), apply(q, (0, -1, 0))}
        graph, _ = physical_graph([p])
        assert (p.uid, 1) in graph[(p.uid, 0)]
        imported = VehicleDocument.parse(xml)
        assert gearbox_ratios(imported.parts[0])["off"]["ratio"] == "1:1"
        assert imported.to_xml(imported.parts) == xml
    schema = definitions.metadata(d)["settings"]
    assert schema["gear_ratio_1"]["default"] == 1 and schema["gear_ratio_2"]["default"] == 0
    assert "max_force_scale" not in schema


def test_cube_gearboxes_are_offered_without_enabling_modular_engines_or_legacy_gearboxes(gearboxes):
    expected = CURRENT_GEARBOXES
    assert {r["definition"] for r in catalogue("transmission", "gearbox")["parts"]} == expected
    assert {r["definition"] for r in definitions.catalogue("gearbox")["parts"]} == expected
    for d in LEGACY_GEARBOXES | {"modular_engine_cylinder"}:
        assert not allowed(d)
        with pytest.raises(ValueError, match="disabled"):
            part({"definition": d, "position": [0, 0, 0]})
    assert allowed("engine")


def test_explicit_editor_ratio_choices_are_preserved(gearboxes):
    settings = {"gear_ratio_1": 6, "gear_ratio_2": 1}
    original = copy.deepcopy(settings)
    p = part({"definition": "modular_engine_gearbox_1x1", "position": [0, 0, 0], "settings": settings})
    assert p.settings == original and settings == original
    row = gearbox_ratios(p)
    assert row["status"] == "configured" and row["off"]["direction"] == "unverified"
    assert row["off"]["ratio"] is None and row["on"]["ratio"] == "1:1"


@pytest.mark.parametrize("value", [-1, True, 1.5, "1", None])
@pytest.mark.parametrize("key", ["gear_ratio_1", "gear_ratio_2"])
def test_new_ratio_indices_require_nonnegative_integers(gearboxes, key, value):
    with pytest.raises(ValueError, match=key):
        part({"definition": "modular_engine_gearbox_1x1", "position": [0, 0, 0], "settings": {key: value}})


@pytest.mark.parametrize("d", sorted(GEARBOXES))
@pytest.mark.parametrize("attributes, direction, invalid", [
    (' gear_ratio_1="0" gear_ratio_2="1"', "reverse", False),
    (' gear_ratio_1="1" gear_ratio_2="0"', "forward", False),
    (' gear_ratio_1="6" gear_ratio_2="0"', "unverified", False),
    (' gear_ratio_1="garbage" gear_ratio_2="0"', "invalid", True),
    (' gear_ratio_1="-1" gear_ratio_2="0"', "invalid", True),
    (' gear_ratio_1="1"', "forward", True),
    ('', "invalid", True),
])
def test_imported_ratio_diagnostics_are_read_only_even_for_deprecated_parts(gearboxes, d, attributes, direction, invalid):
    xml = to_xml([]).replace('<components></components>',
                            f'<components><c d="{d}"><o r="1,0,0,0,1,0,0,0,1"{attributes}>'
                            '<vp/></o></c></components>')
    doc = VehicleDocument.parse(xml)
    report = preflight({"kind": "imported", "source_xml": xml}, doc.parts)
    row = report["gearbox_configuration_checks"][0]
    assert row["off"]["direction"] == direction
    assert (row["status"] == "invalid") == invalid
    assert any(i["issue"].startswith("gearbox off ratio") for i in report["issues"]) == (direction == "reverse")
    assert any(i["issue"] == "gearbox ratios are missing or invalid" for i in report["issues"]) == invalid
    faces = transmission_ports(doc.parts[0])
    graph, _ = physical_graph(doc.parts)
    assert len(faces) == 2 and (doc.parts[0].uid, 1) in graph[(doc.parts[0].uid, 0)]
    assert doc.to_xml(doc.parts) == xml


@pytest.mark.installed
def test_cube_fits_accepted_humvee_shaft_corridor_and_reverse_control():
    if not definitions.definitions_dir():
        pytest.skip("Stormworks installation unavailable")
    from swhull.drafts import export, materialize  # noqa: PLC0415
    from swhull.networks import query  # noqa: PLC0415
    record = {"kind": "land", "spec": {"preset": "humvee_4x4", "bench": "S"}}
    parts, _ = materialize(record)
    gearbox = next(p for p in parts if p.name == "gearbox")
    clutch = next(p for p in parts if p.name == "clutch")
    assert gearbox.piece.d == "modular_engine_gearbox_1x1" and len(gearbox.voxels()) == 1
    assert gearbox.origin == (0, 0, 2)
    assert not any(p.piece.d in LEGACY_GEARBOXES for p in parts)
    face = next(f for f in transmission_ports(gearbox) if f["normal"] == (0, 0, 1))
    assert any(f["position"] == add(face["position"], face["normal"]) and f["normal"] == (0, 0, -1)
               for f in transmission_ports(clutch))
    links = query(record, parts)["links"]
    reverse = next(r for r in links if r["to"]["part_id"] == gearbox.uid and r["type"] == 0)
    assert reverse["from"]["part_id"] == next(p.uid for p in parts if p.name == "driver")
    report = preflight(record, parts)
    assert report["status"] == "connected geometry" and not report["issues"]
    assert report["wire_count"] == 23
    assert all(r["status"] == "connected" for r in report["checks"] if "drivetrain" in r["system"])
    xml, _, _ = export(record)
    doc = VehicleDocument.parse(xml)
    assert preflight({"kind": "imported", "source_xml": xml}, doc.parts)["status"] == "connected geometry"
