# Test models

Every model the suite runs against beyond the Schependomlaan example: five sourced
open-access IFC4 files, and one generated fixture. Both exist because the committed
example is IFC2X3 and declares millimetres, and neither is enough on its own — the
sourced models buy realism, the generated one buys code paths no real open model
reaches. The split is explained under
[What these do *not* cover](#what-these-do-not-cover).

Issue #21 asks for redistributable IFC4 models, and notes that the work is the licence
check rather than the search. This is the result of that check: five models from two
sources, with terms verified at the source, plus the sources that were looked at and
rejected. Issue #20 is the generated fixture, in
[The synthetic fixture](#the-synthetic-fixture).

They live in `examples/data/open/` and are **committed** — 19 MB, on top of the 47 MB
Schependomlaan. `git clone && pytest` covers IFC4, IFC4X3 and metre-declared models with
no fetch step and no network, which is the property #21 wanted to protect. They are the
deliberate exception to the `*.ifc` rule in `.gitignore`.

`examples/fetch_open_models.py` is not needed to use them. It records where each file
came from and its SHA-256, so they can be re-derived and audited rather than being five
binaries of unexplained origin:

```bash
python examples/fetch_open_models.py --verify   # confirm the repo matches the sources
python examples/fetch_open_models.py --list     # sources and terms
```

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
data, and issue #20's synthetic fixture is the way to reach it. That is the honest
division of labour between the two issues: #20 buys the branch, these buy the realism.
That fixture now exists — see [The synthetic fixture](#the-synthetic-fixture) below.

Two smaller gaps worth naming: none of these models has the non-manifold multi-solid
door geometry behind the `process=False` rule, and none has a storey whose geometry sits
far from its declared elevation — the `04 dak` case. Schependomlaan remains the only
fixture with either.

## The synthetic fixture

`examples/data/synthetic/synthetic-ifc4.ifc` (257 KB, committed) is the other half of
the story above. It is not sourced, it is **generated** — by
`examples/make_synthetic_ifc4.py`, which is committed alongside it so the file can be
regenerated and reviewed rather than being an opaque blob:

```bash
python examples/make_synthetic_ifc4.py           # write it
python examples/make_synthetic_ifc4.py --check   # confirm it matches the script
```

`tests/test_synthetic_model.py::test_fixture_matches_its_generator` runs that `--check`,
so the file and the script cannot drift apart.

The comparison is over entities with reals normalised to 9 significant digits, not over
bytes — the header carries a timestamp and an ifcopenshell version, and float rendering
differs between the two ifcopenshell releases the CI matrix pins. Both are differences in
the bytes and neither is a difference in the fixture. A coordinate moved by a micrometre
still fails, and `--check` names the first differing entity and prints both lines.

It is a two-storey, 6.0 × 4.0 m room — four walls per storey, three spaces — declaring
metres. Deliberately shaped to reach what nothing else committed does:

| what | why it is there |
|---|---|
| `IfcPolygonalFaceSet`, one wall subdivided to **3,456 faces** | the branch no open model reaches; the gap to the 6-face walls gives `--max-faces` an unambiguous threshold to sit in |
| `IfcMappedItem` wrapping a **tessellation** | every mapped item in the five open models wraps an extruded solid, so `count_items` recursing into a tessellation was stub-only |
| two storeys, 0.0 m and 3.0 m | section-height selection has a choice to make |
| `IfcSpace`s carrying **only** a `FootPrint` curve | the shape 94 of Schependomlaan's 100 spaces have (#4) — giving them a `Body` would misrepresent real data |

**No licence question**: we wrote it, so it carries none of the terms the models above do.

### What it is not

Clean by construction, and therefore not realistic. It cannot reproduce the authoring
quirks that are the actual source of every geometry bug fixed in this repo — welded
vertices tearing multi-solid elements apart, or storeys whose geometry sits nowhere near
their declared elevation — because we would have to know to put them there. It buys
reachability of code paths, not realism. That is why it complements the open-access
models rather than replacing them, and why the right outcome is for a real IFC4 model
carrying `IfcPolygonalFaceSet` to make it removable one day.

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

## Repo weight, and why committing won

Issue #21 laid out three options: commit, Git LFS, or fetch in CI from a pinned URL.
Committing was chosen. The 19 MB is real, but the alternatives both erode the property
that makes this suite trustworthy — that a fresh clone runs the whole thing. LFS adds a
setup step for everyone who touches the repo, and fetching in CI makes a green build
depend on ifcwiki.org staying up, so a fixture disappearing would take the suite with it.

The checksums in `examples/fetch_open_models.py` are what remains of the fetch approach:
they let anyone confirm that the committed files are the published ones, without the
build depending on those hosts.

If the weight ever needs cutting, `institute` is 10.4 MB of the 19 and the one to drop
first — `fzk-haus` and `smiley-west` between them still give five storeys, 147 spaces,
metres, and the multi-dwelling case.

## In CI

`.github/workflows/tests.yml` needs no fetch step: the models are in the checkout, and
`tests/conftest.py` discovers them, so every matrix leg tests IFC4, IFC4X3 and metres.

That discovery has a failure mode worth knowing about — if the files ever stopped
reaching a checkout, the tests over them would turn into *skips*, and CI would stay green
while testing nothing. `test_all_open_models_are_present` exists to make that a failure
instead, and `test_no_undocumented_open_models` refuses a model that was dropped in
without its licence being recorded here. `test_fixture_is_present` does the same job for
the synthetic file.

The full suite is **222 passed / 7 skipped / 2 xfailed** in about 48 seconds locally,
well inside `timeout-minutes: 15`.

## Adding another one later

1. Verify the licence *at the source* and record it in this file, quoting the terms.
2. Add it to `MODELS` in `examples/fetch_open_models.py` with its URL and SHA-256.
3. Add the filename to `EXPECTED_OPEN_MODELS` in `tests/test_open_models.py`.
4. Run it end to end, not just `--overview`, before committing it.
