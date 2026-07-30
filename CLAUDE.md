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

- **Door geometry** comes out non-rectangular. Suspects: the section height chosen per storey, and `_postprocess_polygons`' `unary_union` merging what should stay separate parts. Windows are likely affected the same way but were filtered out of earlier tests, so it's unconfirmed.
- **Unit handling in `process_storeys`** (`ifc_processor.py:559-566`): intermediate storeys use `(s0.Elevation + s1.Elevation) / 2000` while the last storey uses `s0.Elevation / 1000 + 1.5`. Both hard-code millimetre elevations; the model's `IfcUnitAssignment` is never read.
- `process_ifc_element` swallows all exceptions and returns `None`, so elements silently vanish from output.
- Output is organised per storey only; there is no per-unit/per-dwelling grouping.
