#!/usr/bin/env python3
"""
Generate the synthetic IFC4 fixture in examples/data/synthetic/.

**The fixture is committed.** You do not need to run this to use it - clone the repo
and it is there. This script exists so the file can be regenerated and reviewed rather
than being an opaque blob: every entity in it is written here, in Python, and the
generated file is a deterministic function of this source.

    python examples/make_synthetic_ifc4.py            # write the fixture
    python examples/make_synthetic_ifc4.py --check    # regenerate and diff, write nothing

Why it exists (issue #20). The committed Schependomlaan example is IFC2X3, and
IfcPolygonalFaceSet does not exist in that schema. The five open-access models added in
#29 cover a great deal of IFC4 - IfcTriangulatedFaceSet, IfcMappedItem, metre-declared
units - but between them they contain **zero** IfcPolygonalFaceSet. In the KAAN models
this tool is actually pointed at, that entity carries most of the solid geometry (1,549
in matchbox, 5,015 in spot-a2).

So the branch of `representation_face_count` that reads the dominant body type of every
real model was exercised only by `FakeItem` stubs in tests/test_slow_elements.py. Stubs
assert that the code does what we believe the schema does; they cannot catch the belief
being wrong. Issue #19 was exactly that - a blind spot on IFC2X3 breps that the stubs
did not catch, which made --max-faces silently inert on that whole schema.

What this file is shaped to reach, none of which any committed model reaches today:

- an `IfcPolygonalFaceSet` body, deliberately over-tessellated, so `--max-faces` has
  something real to refuse and the threshold is testable end to end
- an `IfcMappedItem` wrapping a tessellation, so `count_items` recurses into one on a
  real file (the mapped items in the open-access models wrap extruded solids)
- two storeys at different elevations, so section-height selection has a choice to make

What it deliberately does not attempt: realism. A file we generate ourselves is clean by
construction and cannot reproduce the authoring quirks that are the actual source of
every geometry bug fixed here - welded vertices tearing multi-solid elements apart, or
storeys whose geometry sits nowhere near their declared elevation. It buys reachability
of code paths, not realism, which is why it complements the open-access models rather
than replacing them.
"""

import argparse
import sys
from pathlib import Path

import ifcopenshell
import ifcopenshell.guid

DEST = Path(__file__).resolve().parent / "data" / "synthetic"
FILENAME = "synthetic-ifc4.ifc"

# Subdivisions per box side. The tessellated wall is 6 * TESSELLATED**2 faces; the
# rest are plain 6-face boxes. 24 puts the fixture in the hundreds of KB the issue
# asked for and leaves a wide, unambiguous gap for a --max-faces threshold to sit in.
TESSELLATED = 24

# GlobalIds are part of the file's bytes, so a random one per run would make the
# committed fixture unreproducible and every regeneration a large meaningless diff.
# These are derived from a counter instead: stable, and still unique within the file.
_guid_counter = 0


def _guid():
    global _guid_counter
    _guid_counter += 1
    return ifcopenshell.guid.compress("%032x" % _guid_counter)


def box_face_set(f, corner, size, subdivisions):
    """
    A box as an IfcPolygonalFaceSet, each side split into subdivisions**2 quads.

    Subdividing is how the face count is raised without inventing curved geometry:
    the shape stays a box that sections to a clean rectangle, while the entity carries
    as many faces as we ask for. Vertices are shared through `index`, so the solid is
    genuinely closed rather than a soup of coincident corners - ifcopenshell will
    convert the latter, but the result is not watertight and would not section.
    """
    ox, oy, oz = corner
    w, d, h = size
    n = subdivisions

    index, order = {}, []

    def vertex(point):
        key = tuple(round(c, 6) for c in point)
        if key not in index:
            order.append(key)
            index[key] = len(order)  # IFC list indices are 1-based
        return index[key]

    # (corner, u, v) per side, with u x v pointing out of the box so the winding is
    # outward everywhere. Sectioning does not care, but an inside-out solid is the
    # kind of thing that quietly invalidates a fixture later.
    sides = [
        ((ox, oy + d, oz), (w, 0, 0), (0, -d, 0)),   # -Z
        ((ox, oy, oz + h), (w, 0, 0), (0, d, 0)),    # +Z
        ((ox, oy, oz), (w, 0, 0), (0, 0, h)),        # -Y
        ((ox, oy + d, oz), (0, 0, h), (w, 0, 0)),    # +Y
        ((ox, oy, oz), (0, 0, h), (0, d, 0)),        # -X
        ((ox + w, oy, oz), (0, d, 0), (0, 0, h)),    # +X
    ]

    faces = []
    for base, u, v in sides:
        for i in range(n):
            for j in range(n):
                def at(a, b):
                    return tuple(base[k] + u[k] * a / n + v[k] * b / n for k in range(3))
                quad = (at(i, j), at(i + 1, j), at(i + 1, j + 1), at(i, j + 1))
                faces.append(f.create_entity("IfcIndexedPolygonalFace",
                                             CoordIndex=[vertex(p) for p in quad]))

    coordinates = f.create_entity("IfcCartesianPointList3D",
                                  CoordList=[list(p) for p in order])
    return f.create_entity("IfcPolygonalFaceSet", Coordinates=coordinates,
                           Closed=True, Faces=faces)


def build():
    """The whole fixture, as an in-memory ifcopenshell file."""
    f = ifcopenshell.file(schema="IFC4")

    # ── units: metres, so Elevation and --section-offset read on the same scale ──
    units = f.create_entity("IfcUnitAssignment", Units=[
        f.create_entity("IfcSIUnit", UnitType="LENGTHUNIT", Name="METRE"),
        f.create_entity("IfcSIUnit", UnitType="AREAUNIT", Name="SQUARE_METRE"),
        f.create_entity("IfcSIUnit", UnitType="VOLUMEUNIT", Name="CUBIC_METRE"),
    ])

    def point(*coords):
        return f.create_entity("IfcCartesianPoint", Coordinates=tuple(float(c) for c in coords))

    def placement_at(*coords):
        return f.create_entity("IfcAxis2Placement3D", Location=point(*coords))

    world_axes = placement_at(0, 0, 0)
    context = f.create_entity(
        "IfcGeometricRepresentationContext", ContextType="Model",
        CoordinateSpaceDimension=3, Precision=1e-5, WorldCoordinateSystem=world_axes)
    body_context = f.create_entity(
        "IfcGeometricRepresentationSubContext", ContextIdentifier="Body",
        ContextType="Model", ParentContext=context, TargetView="MODEL_VIEW")
    plan_context = f.create_entity(
        "IfcGeometricRepresentationSubContext", ContextIdentifier="FootPrint",
        ContextType="Plan", ParentContext=context, TargetView="PLAN_VIEW")

    world_placement = f.create_entity("IfcLocalPlacement", RelativePlacement=world_axes)

    # ── spatial structure ────────────────────────────────────────────────────
    project = f.create_entity("IfcProject", GlobalId=_guid(), Name="Synthetic IFC4 fixture",
                              UnitsInContext=units, RepresentationContexts=[context])
    site = f.create_entity("IfcSite", GlobalId=_guid(), Name="Site",
                           ObjectPlacement=world_placement, CompositionType="ELEMENT")
    building = f.create_entity("IfcBuilding", GlobalId=_guid(), Name="Building",
                               ObjectPlacement=world_placement, CompositionType="ELEMENT")

    def aggregate(parent, children):
        f.create_entity("IfcRelAggregates", GlobalId=_guid(),
                        RelatingObject=parent, RelatedObjects=list(children))

    storeys = []
    for name, elevation in [("00 ground floor", 0.0), ("01 first floor", 3.0)]:
        storeys.append(f.create_entity(
            "IfcBuildingStorey", GlobalId=_guid(), Name=name,
            ObjectPlacement=f.create_entity("IfcLocalPlacement",
                                            RelativePlacement=placement_at(0, 0, elevation)),
            CompositionType="ELEMENT", Elevation=elevation))

    aggregate(project, [site])
    aggregate(site, [building])
    aggregate(building, storeys)

    # ── walls ────────────────────────────────────────────────────────────────
    # A 6.0 x 4.0 m room, 0.3 m walls, 3.0 m storey height. Sectioned at the default
    # 1.5 m offset every wall is cut through its middle, so a thin result means a real
    # regression rather than a fixture that never had geometry at the cut.
    ROOM = [
        ("south wall", (0.0, 0.0), (6.0, 0.3)),
        ("north wall", (0.0, 3.7), (6.0, 0.3)),
        ("west wall", (0.0, 0.3), (0.3, 3.4)),
        ("east wall", (5.7, 0.3), (0.3, 3.4)),
    ]
    HEIGHT = 3.0

    def tessellated_wall(name, corner_xy, footprint, base_z, subdivisions):
        """A wall whose Body is a polygonal face set in world coordinates."""
        face_set = box_face_set(f, (corner_xy[0], corner_xy[1], base_z),
                                (footprint[0], footprint[1], HEIGHT), subdivisions)
        shape = f.create_entity("IfcShapeRepresentation", ContextOfItems=body_context,
                                RepresentationIdentifier="Body",
                                RepresentationType="Tessellation", Items=[face_set])
        return f.create_entity(
            "IfcWall", GlobalId=_guid(), Name=name, ObjectPlacement=world_placement,
            Representation=f.create_entity("IfcProductDefinitionShape",
                                           Representations=[shape]))

    def mapped_wall(name, corner_xy, footprint, base_z):
        """
        A wall whose Body is an IfcMappedItem wrapping a tessellation.

        The source geometry sits at the local origin and the wall's placement moves it,
        which is what makes this different from the walls above: it exercises the
        recursion in `count_items` *and* the placement path, on a real file rather than
        against a FakeItem that returns whatever we told it to.
        """
        face_set = box_face_set(f, (0.0, 0.0, 0.0), (footprint[0], footprint[1], HEIGHT), 1)
        source_shape = f.create_entity(
            "IfcShapeRepresentation", ContextOfItems=body_context,
            RepresentationIdentifier="Body", RepresentationType="Tessellation",
            Items=[face_set])
        mapped = f.create_entity("IfcMappedItem", MappingSource=f.create_entity(
            "IfcRepresentationMap", MappingOrigin=placement_at(0, 0, 0),
            MappedRepresentation=source_shape), MappingTarget=f.create_entity(
            "IfcCartesianTransformationOperator3D", LocalOrigin=point(0, 0, 0), Scale=1.0))
        shape = f.create_entity(
            "IfcShapeRepresentation", ContextOfItems=body_context,
            RepresentationIdentifier="Body", RepresentationType="MappedRepresentation",
            Items=[mapped])
        placement = f.create_entity(
            "IfcLocalPlacement",
            RelativePlacement=placement_at(corner_xy[0], corner_xy[1], base_z))
        return f.create_entity(
            "IfcWall", GlobalId=_guid(), Name=name, ObjectPlacement=placement,
            Representation=f.create_entity("IfcProductDefinitionShape",
                                           Representations=[shape]))

    def space(name, long_name, corner_xy, footprint, base_z):
        """
        An IfcSpace carrying only a FootPrint curve, the way most real ones do.

        94 of the example model's 100 spaces are FootPrint-only, which is the whole of
        issue #4 - so the fixture would be misleading if its spaces had a Body. The
        outline is a closed IfcPolyline in the Plan context.
        """
        x, y = corner_xy
        w, d = footprint
        ring = [(x, y), (x + w, y), (x + w, y + d), (x, y + d), (x, y)]
        polyline = f.create_entity(
            "IfcPolyline", Points=[point(px, py, 0.0) for px, py in ring])
        shape = f.create_entity(
            "IfcShapeRepresentation", ContextOfItems=plan_context,
            RepresentationIdentifier="FootPrint", RepresentationType="Curve3D",
            Items=[polyline])
        placement = f.create_entity(
            "IfcLocalPlacement", RelativePlacement=placement_at(0, 0, base_z))
        return f.create_entity(
            "IfcSpace", GlobalId=_guid(), Name=name, LongName=long_name,
            ObjectPlacement=placement, CompositionType="ELEMENT",
            Representation=f.create_entity("IfcProductDefinitionShape",
                                           Representations=[shape]))

    def contain(storey, elements):
        f.create_entity("IfcRelContainedInSpatialStructure", GlobalId=_guid(),
                        RelatingStructure=storey, RelatedElements=list(elements))

    # Ground floor: one wall over-tessellated, the rest plain. The gap between 6 faces
    # and 3,456 is what makes a --max-faces threshold unambiguous.
    ground = []
    for i, (name, corner, footprint) in enumerate(ROOM):
        subdivisions = TESSELLATED if i == 0 else 1
        ground.append(tessellated_wall(name, corner, footprint, 0.0, subdivisions))
    contain(storeys[0], ground)
    aggregate(storeys[0], [space("0.01", "woonkamer", (0.3, 0.3), (5.4, 3.4), 0.0)])

    # First floor: the same room with one wall arriving through a mapped item.
    first = [mapped_wall(ROOM[0][0], ROOM[0][1], ROOM[0][2], 3.0)]
    for name, corner, footprint in ROOM[1:]:
        first.append(tessellated_wall(name, corner, footprint, 3.0, 1))
    contain(storeys[1], first)
    aggregate(storeys[1], [
        space("1.01", "slaapkamer", (0.3, 0.3), (2.6, 3.4), 3.0),
        space("1.02", "badkamer", (3.1, 0.3), (2.6, 3.4), 3.0),
    ])

    return f


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[1])
    parser.add_argument("--check", action="store_true",
                        help="regenerate and compare against the committed file, "
                             "writing nothing; exits non-zero if they differ")
    args = parser.parse_args(argv)

    target = DEST / FILENAME
    model = build()

    # ifcopenshell stamps the header with a timestamp and its own version, so two
    # runs never produce byte-identical files. Comparing the entities is the
    # reproducibility that matters and the only one available.
    generated = [str(e) for e in model]

    if args.check:
        if not target.exists():
            print(f"missing: {target}", file=sys.stderr)
            return 1
        committed = [str(e) for e in ifcopenshell.open(str(target))]
        if committed != generated:
            print(f"{target.name} differs from what this script generates "
                  f"({len(committed)} entities committed, {len(generated)} generated). "
                  f"Re-run without --check to update it.", file=sys.stderr)
            return 1
        print(f"{target.name}: {len(generated)} entities, matches this script")
        return 0

    DEST.mkdir(parents=True, exist_ok=True)
    model.write(str(target))
    size_kb = target.stat().st_size / 1024
    print(f"wrote {target} ({size_kb:,.0f} KB, {len(generated)} entities)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
