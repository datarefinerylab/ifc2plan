# Open-access test models

Issue #21 asks for redistributable IFC4 models, and notes that the work is the licence
check rather than the search. This is the result of that check: five models from two
sources, with terms verified at the source, plus the sources that were looked at and
rejected.

Fetch them with:

```bash
python examples/fetch_open_models.py
```

They land in `examples/data/open/`, which is gitignored. Nothing depends on them —
`pytest` passes without them, and tests that use them skip when they are absent, the
same way the private KAAN models do.

## Why the committed example is not enough

`examples/data/Shependomlaan/IFC Schependomlaan.ifc` is **IFC2X3** and declares
**millimetres**. Every model this tool is actually run against is IFC4, and some
authoring tools declare metres. Two things follow:

- the IFC4 geometry entities are unreachable in CI (issue #20)
- the unit conversion in `storey_elevation_metres` is only ever exercised at a scale of
  0.001, so a change that silently assumed millimetres would still pass

Four of the five models below declare **metres** (`1 model unit = 1 m`). That is the
part the committed example cannot test at all.

## The models

Everything in this table was measured by opening the file, not read off a web page.
"Runs clean" means the full extraction was run and reported 0 failed conversions with
every space outline extracted.

| Key | Model | Schema | Units | Size | Storeys | Spaces | Solid geometry | Runs clean |
|-----|-------|--------|-------|------|---------|--------|----------------|------------|
| `fzk-haus` | FZK Haus | IFC4 | m | 2.4 MB | 2 | 7 | 140 `IfcFacetedBrep`, 51 `IfcExtrudedAreaSolid`, 56 `IfcMappedItem` | yes — 177 + 71 intersections |
| `institute` | Office building (Institute Var 2) | IFC4 | m | 10.4 MB | 5 | 82 | 194 `IfcFacetedBrep`, 698 `IfcExtrudedAreaSolid`, 548 `IfcMappedItem` | yes — 2,182 intersections over 5 storeys |
| `smiley-west` | Smiley West, 10 terraced houses | IFC4 | m | 5.8 MB | 5 | 140 | 558 `IfcFacetedBrep`, 950 `IfcExtrudedAreaSolid`, 410 `IfcMappedItem` | yes — 596 intersections on `EG` |
| `pcert-ifc4` | PCERT sample scene, architecture | IFC4 | mm | 220 KB | 1 | 2 | 12 `IfcTriangulatedFaceSet`, 2 `IfcExtrudedAreaSolid` | yes — 7 intersections |
| `pcert-ifc4x3` | PCERT sample scene, architecture | IFC4X3_ADD2 | mm | 216 KB | 1 | 2 | 12 `IfcTriangulatedFaceSet` | yes — 7 intersections |

### What each one is for

- **`fzk-haus`** — the cheapest real IFC4 building. Two storeys, spaces with `FootPrint`
  curves, declared in metres. If only one of these is ever committed, this is the one:
  2.4 MB against the 47 MB the repo already carries.
- **`institute`** — five storeys including a basement at −3.00 m, 82 spaces, and 253
  `IfcFurnishingElement`s that a plan cut has to handle. The largest here, and the one
  to reach for when storey selection or section height is what changed.
- **`smiley-west`** — 10 identical terraced houses in one file, and directly relevant to
  **issue #27**: its spaces are named `<dwelling>.<storey>.<room>` (`05.1.2`, `03.1.3`)
  with `LongName` carrying the room function (`WOHNEN / KOCHEN-05-1`), and there is **no**
  `IfcZone`, `IfcGroup`, or `IfcRelAssignsToGroup` — the same shape of problem as
  Schependomlaan's `7.06`, in a file nobody here authored. A per-dwelling grouping rule
  that works on both is a rule, not a coincidence.
- **`pcert-ifc4` / `pcert-ifc4x3`** — small, and the only files here with tessellated
  bodies. The IFC4X3 one is the only IFC4X3 model in the set; the tool handles it today
  and this is what would catch that changing.

### What these do *not* cover

**`IfcPolygonalFaceSet` does not appear in any of them.** All five are ArchiCAD 20 or
SketchUp exports, and neither writes that entity — it is what the Revit-family exporters
produce, which is why the private KAAN models are full of it (1,549 and 5,015 in the two
counted in issue #20) and no open model checked here has a single one. A GitHub-wide
search for the entity inside `.ifc` files returns component libraries and viewer test
assets, not buildings.

So the primary branch of `representation_face_count` stays unreachable from real open
data, and issue #20's synthetic fixture is still the way to reach it. That is the honest
division of labour between the two issues: #20 buys the branch, these buy the realism.

Two smaller gaps worth naming: none of these models has the non-manifold multi-solid
door geometry behind the `process=False` rule, and none has a storey whose geometry sits
far from its declared elevation — the `04 dak` case. Schependomlaan remains the only
fixture with either.

## Licences

### buildingSMART Sample-Test-Files — CC BY 4.0

Source: <https://github.com/buildingSMART/Sample-Test-Files> (`pcert-ifc4`,
`pcert-ifc4x3`). The repository `LICENSE` reads, in full:

> (C) buildingSMART International Ltd.
>
> This work is licensed under the Creative Commons Attribution 4.0 International License.
> More info and a link to the full license text is available on
> http://creativecommons.org/licenses/by/4.0/

Redistribution is permitted with attribution to **buildingSMART International Ltd.**

One caveat, recorded because it bears on the model we already ship: this repository was
purged and relicensed on 2024-11-06 (commit `451fae1f` "purge", then `92211eb4` "Create
LICENSE"). The CC BY 4.0 file covers what is in the tree *now*. Schependomlaan is no
longer in it — `openBIMstandards/DataSetSchependomlaan` now redirects to this repository,
to a path that does not exist on `main`. Our copy therefore predates the current licence
file, and its provenance chain is not established by it. Worth resolving separately;
it is not a blocker for anything here.

### KIT / IAI models — unrestricted use, attribution requested

Source: <https://www.ifcwiki.org/index.php?title=KIT_IFC_Examples> (`fzk-haus`,
`institute`, `smiley-west`). The terms are stated on that page, verbatim:

> These examples are made by the Institute for Applied Computer Science (IAI) at the
> Karlsruhe Institute of Technology (KIT), and are for **unrestricted use**. If you use
> these examples for publications, please provide the following **source**: Institute for
> Automation and Applied Informatics (IAI) / Karlsruhe Institute of Technology (KIT) or
> Institut für Automation und angewandte Information / Karlsruher Institut für Technologie

This is a permission grant rather than a named licence, so read it as written: use is
unrestricted, which covers redistribution, and attribution is requested specifically for
publications. **This project has a publication planned, so that request applies to us** —
the attribution line above needs to travel into the paper, not just this file.

### Rejected: Open IFC Model Repository (University of Auckland)

<https://openifcmodel.cs.auckland.ac.nz/>. re3data records the data upload licence as
CC-BY-3.0, but the site is a JavaScript application with no server-rendered listing, its
`/api/download/<id>` endpoint returned 404 for the model IDs tried, and it has
login/register routes — downloads appear to be account-gated. Its holdings are also
re-published from other projects (BLIS, DDS, FZK, IAI, NIST, Statsbygg), so a
repository-wide licence statement would not settle any individual file's terms anyway.
Not usable as a pinned fixture source. The FZK models it carries are available directly
from KIT, on the clearer terms above.

## Keeping them

They are fetched, not committed, and `examples/data/open/` is gitignored — which leaves
issue #21's repo-weight question open rather than answering it by default. To commit one
after deciding:

```bash
git add -f examples/data/open/AC20-FZK-Haus.ifc
```

`fzk-haus` is the candidate that survives that decision most easily: 2.4 MB, IFC4,
metres, two storeys, spaces with footprints.

Each entry in `examples/fetch_open_models.py` pins a URL and the SHA-256 of the resulting
`.ifc`. If a host changes a file, the fetch reports the mismatch instead of quietly
handing back different geometry.

## Wiring them into CI

Not done here, because it is the same repo-weight decision. `.github/workflows/tests.yml`
is untouched, so CI still runs exactly what it ran before. Whichever way #21 is settled,
the test side already works:

- **committed** — nothing else to do; the models are simply present and the tests run
- **fetched in CI** — one step before `pytest`:

  ```yaml
  - name: Fetch open-access test models
    run: python examples/fetch_open_models.py fzk-haus pcert-ifc4
  ```

  which adds ~2.7 MB and, measured locally, about 4 seconds of test time — comfortably
  inside `timeout-minutes: 15`. The cost is that a green build then depends on
  ifcwiki.org and raw.githubusercontent.com being reachable.

Locally the full suite goes from 134 passed / 6 skipped to **161 passed / 6 skipped**
with all five fetched, in 32 seconds.
