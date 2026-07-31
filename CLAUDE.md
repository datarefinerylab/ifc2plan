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
- Branches: only `main` exists on origin. Work happens on `main`.
- No packaging (`pyproject.toml` / `setup.py` do not exist), no CI, no test suite.
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

## Running It

Imports are flat (`from geometry_engine import ...`), so **the CLI only works from inside `src/ifc2plan/`**:

```bash
cd src/ifc2plan
python extract_floor_plans.py "../../examples/data/Shependomlaan/IFC Schependomlaan.ifc" --overview
python extract_floor_plans.py "../../examples/data/Shependomlaan/IFC Schependomlaan.ifc" \
  --storey 0 --formatter image wkt --colored-spaces \
  --naming-conversion ../../naming_conversion.csv --output ../../output
```

The README's examples assume this too, without saying so.

Geometry engine self-test: `cd src/ifc2plan && python geometry_engine.py`.

## Environment

Dependencies are in `requirements.txt` (ifcopenshell, shapely, trimesh, numpy, pillow, matplotlib, pandas, tqdm, networkx, scipy). **No virtualenv is committed and the system `python3` (3.9.6) does not have them installed.** Before running anything, check for an active env; if there is none, create `.venv` and install from `requirements.txt` — ask first, don't silently install into system Python.

## Working Agreements

- **Verify on real data.** There are no unit tests for the IFC path. A change is not "done" until it has been run against the Schependomlaan example and the resulting geometry/image inspected.
- **Never commit** `output/`, generated PNG/CSV, or new large IFC files.
- **Don't push or open PRs without being asked.** `origin` is a shared lab repo.
- No upstream to keep compatible with — the fork was detached and upstream was dormant.
  History is still worth keeping clean, but for our own sake, not for merge-back.
- When touching `naming_conversion.csv`: it has a blank-original row mapping to `not defined`; `load_naming_conversion` reads it with pandas, so blank/NaN cells have caused `AttributeError: 'float' object has no attribute 'lower'` before.

## Known Weak Spots

Useful priors when debugging — verify before acting on any of them:

- **Section height is the biggest remaining defect** (issue #3). `process_storeys`
  (`ifc_processor.py:559-566`) uses `(s0.Elevation + s1.Elevation) / 2000` for
  intermediate storeys and `s0.Elevation / 1000 + 1.5` for the last one. Three separate
  problems:
  - **`--storey N` and a full run disagree on the height of the same storey.** The
    single-storey path replaces the list (`storeys = [storeys[storey_index]]`, line 548),
    so `idx == 0` and `len(storeys) == 1` always take the *last-storey* branch. Storey
    `[0]` is cut at −0.50 m in a full run but +0.50 m under `--storey 0`. A single-storey
    run therefore cannot be used to verify full-run behaviour, and a "storey 0 is empty"
    report from `--storey 0` is not evidence of anything.
  - **The declared unit is never read.** Both branches hard-code millimetres. This model
    declares `MILLI METRE` so `/1000` is accidentally right. Note the asymmetry that makes
    it confusing: `IfcBuildingStorey.Elevation` is in raw **model units** (6000), while
    ifcopenshell hands back geometry already converted to **metres** (5.91).
    `ifcopenshell.util.unit.calculate_unit_scale(model)` returns 0.001 here and is the
    conversion to use.
  - **A fixed offset above the storey datum does not suit non-habitable storeys.** Their
    geometry is not where the datum implies: `-1 fundering` sits at z −1.700…−0.090 m
    (*below* its own −1.0 m elevation), and `04 dak` at 11.620…13.113 m against a 12.0 m
    elevation. A 1.5 m offset puts the plane above every roof element — which is why
    `04 dak` produces **no intersections at all** today — and would put storey 0 at
    +0.50 m, losing the 93 intersections a full run currently finds. Any offset rule needs
    a documented fallback for planes that fall outside a storey's actual geometry.
- **Counters on the geometry engine are per element, not per solid.** `intersect_with_plane`
  sections each solid separately, so anything counted inside `_closed_rings` counts solids.
  `elements_affected` is bumped once per element by `intersect_with_plane` itself for this
  reason; `open_fragments` / `unusable_rings` are genuine per-solid totals. Keep that split
  if you add a counter, and it is a usable before/after metric for element loss.
- **Don't build a mesh with `trimesh.Trimesh(verts, faces)` and default processing.** Trimesh welds vertices that share a position, and in an IFC element those are the corners where separate solids touch (door leaf against frame). Welding fuses them into one torn, non-manifold surface — door 670101 went from 20 watertight solids and 0 broken faces to 68 fragments and 234 broken faces. `process=False` plus sectioning each solid separately is why door/window geometry is now correct; both are load-bearing, and `process=False` alone changes nothing because trimesh welds again when building a section path.
- `process_ifc_element` swallows all exceptions and returns `None`, so elements silently vanish from output.
- Output is organised per storey only; there is no per-unit/per-dwelling grouping.
