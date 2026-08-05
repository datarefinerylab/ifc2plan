# ifc2plan — Claude Context

Extracts 2D floor plans and geometric data (WKT/CSV + PNG) from IFC building models.
Research tool; outputs feed downstream ML / analysis work and a planned publication.

## Repo Facts

- Remotes: `origin` → `datarefinerylab/ifc2plan`. Single remote, and the repo is **not**
  a fork, so `gh` has nothing to mis-resolve. (`gh repo set-default` is still per-clone —
  it lives in `.git/config` as `remote.origin.gh-resolved`, which is not committed.)
- **History starts at the truncated root**, not at the original project. This repo was
  `datarefinerylab/BatchPlan`, itself a fork of `byildiz/BatchPlan` (fork point
  `4958a6f`, MIT, © 2024 Burak Yildiz). The 49 upstream commits were **removed** from
  this repo's history; the root commit records the derivation and the original history
  lives on in `byildiz/BatchPlan`. Attribution is in `LICENSE` and README "Origin" —
  those are the MIT notice-retention, so don't drop them. `datarefinerylab/BatchPlan`
  is archived and read-only and still holds the pre-truncation history; don't push to
  `batchplan-archived` if that remote still exists locally. Upstream was dormant at the
  time of the split, so there is no upstream to sync with or send PRs to.
- Branches: work happens on a short-lived branch and lands on `main` via PR — every
  change since the root cut has. **`main` is the only branch on origin**; merged PR
  branches are deleted once they land. (Six leftovers were swept up in the cleanup that
  added this note. One of them, `docs/readme-corrections`, was not an ancestor of `main`
  — commit `a3906a6` was pushed after PR #23 merged and then redone as `74c466d` in #24.
  The two trees were byte-identical, so nothing was lost.)
  `backup/pre-root-cut` is **local-only** and holds the pre-truncation history; it has
  no remote, so nothing else is protecting it — don't delete it in a branch cleanup.
- No packaging — `pyproject.toml` / `setup.py` do not exist, and the flat imports
  depend on that (see "Running It").
- There **is** CI and a test suite: `.github/workflows/tests.yml` runs pytest on every
  PR and on pushes to `main`, matrixed over Python 3.9 and 3.13 (deliberately different
  `ifcopenshell` versions — 3.9 pins 0.8.4.post1, the last release supporting it).
  `tests/` holds 9 files that collect to ~158 tests, driven by `pytest.ini`; run them
  with `pytest` from the repo root (146 passed / 10 skipped / 2 xfailed on a machine
  without the private models). Markers: `example` (committed public model),
  `private` (gitignored KAAN models, auto-skips), `slow` (full run over a large model). `tests/conftest.py` puts `src/ifc2plan` on `sys.path` so tests
  import exactly the way the CLI does, and it discovers models rather than hardcoding
  them — the Schependomlaan example is always present, and tests over the gitignored
  KAAN client data skip cleanly when it's absent.
- Example data: `examples/data/Shependomlaan/IFC Schependomlaan.ifc` (47 MB, committed).

## Layout

| Path | Responsibility |
|------|----------------|
| `src/ifc2plan/extract_floor_plans.py` | CLI entry point: argparse, builds the `context` dict, loops over IFC files |
| `src/ifc2plan/ifc_processor.py` | IFC loading, storey iteration, section-height calc, element filters, room-type lookup, mesh extraction |
| `src/ifc2plan/geometry_engine.py` | `ShapelyTrimeshEngine`: mesh↔plane intersection, polygon validation/merging; inline `test_geometry_engine()` |
| `src/ifc2plan/formatters.py` | `FloorPlanImageFormatter` (4 styles, legends, scale bar, north arrow), `FloorWKTFormatter` (CSV/WKT) |
| `naming_conversion.csv` | Room-name mapping (Dutch → English), `original,english` |

Data flow: `IFC → ifcopenshell.geom.create_shape → trimesh.Trimesh → mesh.section(z=section_height) → Shapely polygons → formatters`.

Everything is passed around in a single `context` dict (args, engine, filter_fn, style, naming_conversion, formatters, storey_index …). There is no config object or class hierarchy beyond the engine/formatter ABCs.

## Section Height

How the cutting plane is chosen, since issue #3 rewrote this and the old rule
(`(s0.Elevation + s1.Elevation) / 2000`, hard-coded millimetres) is gone:

1. `storey_elevation_metres` converts the storey datum to metres via
   `calculate_unit_scale`. The declared unit is read, not assumed.
2. The plane goes at `elevation + section_offset`, where the offset is
   `--section-offset` (default 1.5 m, the conventional plan cut). One rule for every
   storey — `--storey N` and a full run now agree on the same storey's height.
3. If that plane falls outside the storey's actual geometry, `best_covering_height`
   picks the height crossing the most meshes and the run says so. This is what makes
   non-habitable storeys work: `04 dak` (geometry 11.62–13.11 m against a 12.0 m datum)
   used to produce **zero** intersections and now falls back to 12.03 m for 158.
4. Elements that do not reach the chosen plane are reported by type, so a thin result
   is visible rather than silent.

Spaces bypass all of this — a room's `FootPrint` curve already is its plan outline, so
`space_outline_polygon` is used instead of sectioning (issue #4).

## Running It

Imports are flat (`from geometry_engine import ...`) and there is no packaging, so the
script must be **invoked by its path** — Python then puts `src/ifc2plan/` on `sys.path`
itself and the imports resolve. Running from the repo root is fine:

```bash
python src/ifc2plan/extract_floor_plans.py "examples/data/Shependomlaan/IFC Schependomlaan.ifc" --overview
python src/ifc2plan/extract_floor_plans.py "examples/data/Shependomlaan/IFC Schependomlaan.ifc" \
  --storey 0 --formatter image wkt --colored-spaces \
  --naming-conversion naming_conversion.csv --output output
```

What does *not* work is a bare `python extract_floor_plans.py` from anywhere but
`src/ifc2plan/`, because the file is not there. (This file previously claimed the CLI
only worked from inside `src/ifc2plan/`; that was wrong, and the README's examples were
written around the mistaken version.)

Geometry engine self-test: `python src/ifc2plan/geometry_engine.py`. (CI runs it as
`python geometry_engine.py` with `working-directory: src/ifc2plan`; both work.)

## Environment

Dependencies are in `requirements.txt` (ifcopenshell, shapely, trimesh, numpy, pillow, matplotlib, pandas, tqdm, networkx, scipy). **No virtualenv is committed and the system `python3` (3.9.6) does not have them installed.** Before running anything, check for an active env; if there is none, create `.venv` and install from `requirements.txt` — ask first, don't silently install into system Python.

## Working Agreements

- **Verify on real data.** `pytest` covers the IFC path now and is the first gate — but it is not the last one. Geometry can pass every assertion and still be visibly wrong, so a change is not "done" until it has also been run against the Schependomlaan example and the resulting geometry/image inspected.
- **Never commit** `output/`, generated PNG/CSV, or new large IFC files.
- **Don't push or open PRs without being asked.** `origin` is a shared lab repo. When you are asked, branch — never commit straight to `main`.
- No upstream to keep compatible with — the fork was detached and upstream was dormant.
  History is still worth keeping clean, but for our own sake, not for merge-back.
- When touching `naming_conversion.csv`: it has a blank-original row mapping to `not defined`; `load_naming_conversion` reads it with pandas, so blank/NaN cells have caused `AttributeError: 'float' object has no attribute 'lower'` before.

## Known Weak Spots

Useful priors when debugging — verify before acting on any of them:

- **Units are the trap in anything touching heights** (the rest of issue #3 is fixed —
  see "Section Height" above). `IfcBuildingStorey.Elevation` is in raw **model units**
  (6000 here), while ifcopenshell hands back geometry already converted to **metres**
  (5.91). Never compare the two directly: go through `storey_elevation_metres`, which
  applies `ifcopenshell.util.unit.calculate_unit_scale(model)` (0.001 on this model).
- **Counters on the geometry engine are per element, not per solid.** `intersect_with_plane`
  sections each solid separately, so anything counted inside `_closed_rings` counts solids.
  `elements_affected` is bumped once per element by `intersect_with_plane` itself for this
  reason; `open_fragments` / `unusable_rings` are genuine per-solid totals. Keep that split
  if you add a counter, and it is a usable before/after metric for element loss.
- **Don't build a mesh with `trimesh.Trimesh(verts, faces)` and default processing.** Trimesh welds vertices that share a position, and in an IFC element those are the corners where separate solids touch (door leaf against frame). Welding fuses them into one torn, non-manifold surface — door 670101 went from 20 watertight solids and 0 broken faces to 68 fragments and 234 broken faces. `process=False` plus sectioning each solid separately is why door/window geometry is now correct; both are load-bearing, and `process=False` alone changes nothing because trimesh welds again when building a section path.
- **`_convert` swallows every exception and returns `None`** (`geometry_engine.py:574-579`),
  so a failed element is counted in the `❌ Failed conversions` line and nowhere else —
  no id, no type, no reason (issue #26). On the example this hides 4 elements of 3,573,
  all `IfcWall 'dakopstand'` on `04 dak` carrying only an `Axis`/`Curve2D` representation
  with no `Body`. Note the asymmetry: the space path *does* report reasons —
  `space_outline_polygon` returns `(polygon, reason)` and the caller prints it.
- Output is organised per storey only; there is no per-unit/per-dwelling grouping
  (issue #27). The example is 10 apartments, so a storey file mixes 2–3 of them. The
  dwelling is in `IfcSpace.Name` as `<dwelling>.<room>` (`7.06`), with `A0`–`A3` as
  per-storey common space — there is **no** `IfcZone`/`IfcGroup`/`IfcRelAssignsToGroup`
  in this file, so nothing can be read from the spatial hierarchy. Space rows carry the
  name through to the CSV; wall/door/slab rows are `IfcWall_1001928` and cannot be
  attributed to a dwelling at all.
