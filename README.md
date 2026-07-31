# ifc2plan

[![Python 3.9+](https://img.shields.io/badge/python-3.9+-blue.svg)](https://www.python.org/downloads/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)

> Extract geometric data (CSV/WKT) and 2D floor plans from IFC building models

## Features

📊 **Export geometric data** as WKT/CSV
✨ **Professional floor plan images** with architectural styling
🎨 **Multiple visual styles** (professional, minimal, colorful, technical)
🌈 **Colored room type visualization** with customizable legends
🏠 **Room naming conversion** (e.g., Dutch to English)
⚡ **Batch processing** for multiple IFC files
🔧 **Robust geometry engine** using Trimesh + Shapely    

## Installation

**Requirements:** Python 3.9+ — this is set by `ifcopenshell`, which no longer publishes
wheels for 3.8. The test suite runs on 3.9 and 3.13.

```bash
git clone https://github.com/datarefinerylab/ifc2plan.git
cd ifc2plan
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
```

> [!NOTE]
> The project is not packaged and its modules import each other by bare name
> (`from geometry_engine import ...`), so **invoke the script by its path**
> — `python src/ifc2plan/extract_floor_plans.py`. Python puts the script's own directory
> on `sys.path`, which is what makes those imports resolve. A bare
> `python extract_floor_plans.py` only works if you have already `cd`'d into
> `src/ifc2plan/`.

## Quick Start

A model is included, so these run as written on a fresh clone, from the repository root:

```bash
EXAMPLE="examples/data/Shependomlaan/IFC Schependomlaan.ifc"

# Show file overview: storeys, element counts. Fast - no geometry processing.
python src/ifc2plan/extract_floor_plans.py "$EXAMPLE" --overview

# Extract one storey as CSV/WKT (much faster than all storeys)
python src/ifc2plan/extract_floor_plans.py "$EXAMPLE" --storey 2

# Floor plan images with colored room types
python src/ifc2plan/extract_floor_plans.py "$EXAMPLE" \
  --storey 2 --formatter image wkt --colored-spaces \
  --naming-conversion naming_conversion.csv
```

Output lands in `output/IFC Schependomlaan/`.

## Usage

```bash
# Basic usage: all storeys, WKT only, professional black & white style
python src/ifc2plan/extract_floor_plans.py building.ifc

# Extract only spaces with colored room types from one storey
python src/ifc2plan/extract_floor_plans.py building.ifc \
  --storey 0 \
  --space-only \
  --colored-spaces \
  --naming-conversion naming_conversion.csv

# Generate both colored and black & white versions
python src/ifc2plan/extract_floor_plans.py building.ifc \
  --both \
  --naming-conversion naming_conversion.csv

# Multiple outputs and styling for a specific storey
python src/ifc2plan/extract_floor_plans.py building.ifc \
  --storey 2 \
  --output ./plans \
  --formatter image wkt \
  --style colorful \
  --colored-spaces \
  --width 4096

# Batch process multiple files
python src/ifc2plan/extract_floor_plans.py "buildings/*.ifc" --output ./all_plans
```

### Command Line Options

| Option | Description | Default |
|--------|-------------|---------|
| `--overview` | Show IFC file overview without processing geometry | `False` |
| `--storey INDEX` | Process only specific storey by index (0-based) | All storeys |
| `--section-offset` | Cutting plane height above each storey's elevation, in metres | `1.5` |
| `--output` | Output directory | `output` |
| `--formatter` | Output format: `image`, `wkt` (space-separated) | `wkt` |
| `--style` | Visual style: `professional`, `minimal`, `colorful`, `technical` | `professional` |
| `--colored-spaces` | Color spaces by room type (requires naming conversion) | `False` |
| `--both` | Generate both colored and black & white versions | `False` |
| `--space-only` | Extract only IfcSpace elements | `False` |
| `--naming-conversion` | CSV file for room name translation (format: `original,english`) | `None` |
| `--width/--height` | Image dimensions (pixels) | `2048` |
| `--max-elements` | Limit for large files (testing) | `None` |
| `--slow-element-seconds` | Report any element slower than this to convert | `5.0` |
| `--max-faces` | Skip elements declaring more faces than this (trades completeness for speed) | `None` |

### When a run is unexpectedly slow

Conversion time is usually concentrated in a very small number of heavily
tessellated elements. On one storey of a real model, four elements out of 669
accounted for 99% of the time — over half an hour, with nothing in the output
saying which ones they were.

Those elements are now named as they are converted, and summarised at the end of
each storey:

```
   ⏱  Slow element: IfcCovering #462475 '47_GM_waterslag' (26,011 faces) took 157.8s

   ⏱  4 slow element(s), 309s total:
        157.8s  IfcCovering #462475 '47_GM_waterslag' (26,011 faces)
         86.5s  IfcCovering #504259 '47_GM_waterslag' (26,011 faces)
```

If you do not need that geometry, `--max-faces` skips it. On the storey above,
`--max-faces 12000` takes the mesh pass from **162 s to 5.6 s** at the cost of
those four elements (655 meshes → 651).

Pick the threshold from the report rather than guessing: the face count is a
coarse proxy for cost, not a direct one. In that model a 10,239-face door
converts in 0.66 s while a 15,736-face covering takes 23 s, so a limit set too
low discards geometry without buying time. The flag is off by default for the
same reason — it changes output.

Face counts are read from the representation itself and cover tessellated bodies
(`IfcPolygonalFaceSet`, `IfcTriangulatedFaceSet`), brep solids (`IfcFacetedBrep`
and the rest of the `IfcManifoldSolidBrep` family), surface models, and mapped
items wrapping any of those. Anything else counts as zero, so an element with an
unrecognised body type is never skipped — a body type this does not know about
makes the flag do less, never more. Swept solids such as `IfcExtrudedAreaSolid`
have no declared face count and so are always converted.

## Output Structure

```
output/
└── building_name/
    ├── Level_1_floor_plan.png          # Floor plan image (b&w by default)
    ├── Level_1_floor_plan_colored.png  # Colored version (if --both or --colored-spaces)
    ├── Level_1_floor_plan_bw.png       # Black & white version (if --both)
    ├── Level_1_floor_plan.csv          # Geometric data (WKT format)
    └── Level_2_floor_plan.png
    ...
```

The CSV columns are `type`, `name`, `room_type`, `room_type_original`, `geometry`.
`room_type` is the converted and normalised value; `room_type_original` is the room's
name exactly as the model gives it, so rooms with no entry in the naming conversion are
still identifiable.

## Room Naming Conversion

Create a CSV file with room name translations (e.g., Dutch to English):

```csv
original,english
badkamer,bathroom
slaapkamer,bedroom
woonkamer,livingroom
keuken,kitchen
gang,corridor
berging,storage
balkon,balcony
```

Then use it with:
```bash
python src/ifc2plan/extract_floor_plans.py building.ifc \
  --colored-spaces --naming-conversion naming_conversion.csv
```

## Visual Styles

The tool supports four visual styles, each with optional room type coloring:

### Professional (Default)
Clean architectural style with subtle colors. When `--colored-spaces` is enabled, each room type gets a distinct pastel color.

### Minimal
Black and white style with grayscale room differentiation when colored mode is enabled.

### Colorful
Bright, vibrant colors for presentations. Room types use highly saturated colors in colored mode.

### Technical
Line-only drawings with no fills (architectural drafting style). Room coloring is not applicable.

## Examples

<details>
<summary>📸 View example outputs</summary>

### Professional
Default output with uniform space coloring
![Professional floor plan example](assets/professional.png)

### Professional Style with Colored Room Types
With `--colored-spaces` flag, each room type has a distinct color
![Colored floor plan example](assets/professional_colored.png)

### Technical Style (Line drawings)
![Technical floor plan example](assets/technical.png)

</details>

## Troubleshooting

**No floor plans generated?**
- Ensure your IFC file contains `IfcBuildingStorey` elements
- Try `--max-elements 100` for testing large files
- Check that `--formatter image` is specified if you want image outputs

**Room types not colored?**
- Ensure you use `--colored-spaces` flag
- Provide a naming conversion CSV with `--naming-conversion`
- Check that room names in IFC match entries in your CSV (case-insensitive)

**`can't open file 'extract_floor_plans.py'`, or `ModuleNotFoundError`?**
- Invoke the script by its path: `python src/ifc2plan/extract_floor_plans.py` — see
  [Installation](#installation)

**Memory issues?**
- Use `--max-elements` to limit processing
- Process files individually instead of batch
- A parsed IFC model is roughly 6× its file size in RAM, so a 200 MB file wants ~1.2 GB.
  `--parallel` holds one copy per worker and sizes the pool against available memory
  for that reason

**Processing very slow?**
- Read the `⏱` lines. Time is usually concentrated in a handful of heavily tessellated
  elements rather than spread across the model — see
  [When a run is unexpectedly slow](#when-a-run-is-unexpectedly-slow)
- `--max-faces` skips those elements if you do not need them, at the cost of dropping
  their geometry
- `--parallel` opens the model once per worker and processes elements across cores

## Origin

`ifc2plan` began as a fork of [byildiz/BatchPlan](https://github.com/byildiz/BatchPlan)
and was renamed after diverging substantially from it. It is a derivative work, MIT
licensed, and the original copyright is retained — see [LICENSE](LICENSE).

- Derived from [`byildiz/BatchPlan@4958a6f`](https://github.com/byildiz/BatchPlan/commit/4958a6f).
  This repository's history was truncated to its own work, so the original commits are
  **not** in this history — they remain in `byildiz/BatchPlan`. The root commit here
  records the derivation.
- The OpenCASCADE/SWIG geometry pipeline of the original was replaced with a
  [Trimesh](https://trimsh.org/) + [Shapely](https://shapely.readthedocs.io/) engine
  (`src/ifc2plan/geometry_engine.py`, `src/ifc2plan/ifc_processor.py`).
- The original's material/LCA database tooling was removed; this repository is scoped to
  floor plan and geometry extraction.

The former repository, `datarefinerylab/BatchPlan`, is archived and read-only.

---

**Built with:** [IfcOpenShell](https://ifcopenshell.org/) • [Trimesh](https://trimsh.org/) • [Shapely](https://shapely.readthedocs.io/)