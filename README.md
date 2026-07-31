# ifc2plan

[![Python 3.9+](https://img.shields.io/badge/python-3.9+-blue.svg)](https://www.python.org/downloads/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)

**Turn an IFC building model into 2D floor plans — as images you can look at, or as data you can analyse.**

For each storey of a model, ifc2plan cuts a horizontal section through the building and writes:

- a **floor plan image** (PNG), in one of four drawing styles, optionally coloured by room type
- a **table of the shapes** (CSV), one row per element, so you can measure, count, or feed it into other tools

![Floor plan of the ground floor of the bundled example model, with rooms coloured by type](assets/professional_colored.png)

*The ground floor of the example building included in this repository — produced by step 3
below, unedited.*

## Install

You need **Python 3.9 or newer**.

```bash
git clone https://github.com/datarefinerylab/ifc2plan.git
cd ifc2plan
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
```

On Windows, use `.venv\Scripts\activate` instead of `source .venv/bin/activate`.

## Run it

Stay in the `ifc2plan` folder and give the **full path to the script**, exactly as shown below.
An example building is included, so you can copy these lines as they are.

**1. Look inside the file first.** This is instant — it lists the storeys and how many
elements each one has, and tells you the storey numbers you'll need.

```bash
python src/ifc2plan/extract_floor_plans.py "examples/data/Shependomlaan/IFC Schependomlaan.ifc" --overview
```

**2. Draw one floor plan.** Storey `1` is the ground floor of this building — step 1 told
you that.

```bash
python src/ifc2plan/extract_floor_plans.py "examples/data/Shependomlaan/IFC Schependomlaan.ifc" \
  --storey 1 --formatter image
```

**3. Draw it with rooms coloured by type, and get the data too.** This is the drawing at
the top of this page.

```bash
python src/ifc2plan/extract_floor_plans.py "examples/data/Shependomlaan/IFC Schependomlaan.ifc" \
  --storey 1 --formatter image wkt --colored-spaces \
  --naming-conversion naming_conversion.csv
```

Results appear in `output/IFC Schependomlaan/`.

To use your own model, put its path in place of the example. **Start with `--overview`,
then one storey** — a whole building takes a while, and there is no point waiting for it
until you know the settings are right. Leave `--storey` off to do every storey.

> **On the long command:** always type the full `src/ifc2plan/extract_floor_plans.py`.
> The short `python extract_floor_plans.py` fails unless you have moved into that folder
> first. If you get `can't open file` or `ModuleNotFoundError`, this is why.

## Options

| Option | What it does | Default |
|--------|--------------|---------|
| `--overview` | List storeys and element counts, then stop. Costs nothing — always start here | off |
| `--storey N` | Do one storey only. `N` is the number shown by `--overview`, counting from 0 | all storeys |
| `--formatter` | What to write: `image`, `wkt`, or both (`--formatter image wkt`) | `wkt` |
| `--output` | Folder to write into | `output` |
| `--style` | Look of the drawing: `professional`, `minimal`, `colorful`, `technical` | `professional` |
| `--colored-spaces` | Give each room type its own colour (needs `--naming-conversion`) | off |
| `--both` | Write a coloured *and* a black & white version | off |
| `--space-only` | Draw only the rooms, leaving out walls, doors, and everything else | off |
| `--naming-conversion` | CSV that translates room names — see [Room names](#room-names) | none |
| `--width`, `--height` | Image size in pixels | `2048` |
| `--section-offset` | How high above each floor to cut, in metres | `1.5` |
| `--parallel` | Use several processor cores at once | off |
| `--max-faces` | Skip unusually detailed elements to save time — see [If a run is slow](#if-a-run-is-slow) | none |
| `--max-elements` | Stop after this many elements. Useful for a quick trial run on a big file | none |
| `--slow-element-seconds` | Report any element that takes longer than this to convert | `5.0` |
| `--skip-failed` | Keep going when an element fails instead of stopping | off |

## What you get

Files are named after the storey as the model names it, inside a folder named after the
model. Running example 3 above gives you:

```
output/
└── IFC Schependomlaan/
    ├── 00 begane grond_floor_plan.png   # the drawing
    └── 00 begane grond_floor_plan.csv   # the data
```

With `--both` you get two drawings per storey instead of one, marked `_colored` and `_bw`:

```
    ├── 00 begane grond_floor_plan_colored.png
    └── 00 begane grond_floor_plan_bw.png
```

Each row of the CSV is one element, with these columns:

| Column | Meaning |
|--------|---------|
| `type` | What it is in the model — `IfcWall`, `IfcSpace`, `IfcDoor`, … |
| `name` | The element's name from the model |
| `room_type` | The tidied, translated room type |
| `room_type_original` | The room name exactly as the model spells it, so rooms you haven't translated are still identifiable |
| `geometry` | The outline itself, as WKT — a text format that QGIS, PostGIS, Shapely, and R can all read directly |

## Room names

Models often name rooms in the local language. Give ifc2plan a two-column CSV and it will
translate them, which is also what lets it colour rooms by type. `naming_conversion.csv`
in this repository is a Dutch → English starting point:

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

Add your own rows in the same format. Matching ignores capitals. Rooms with no matching
row still appear in the output — you'll see them under their original name in the
`room_type_original` column.

## Drawing styles

| `--style` | Looks like |
|-----------|------------|
| `professional` *(default)* | Clean architectural drawing with subtle fills |
| `minimal` | Black and white; rooms separated by shades of grey |
| `colorful` | Bright and saturated, for slides and posters |
| `technical` | Outlines only, no fills, like a drafting sheet. Room colouring does not apply |

Every style can be combined with `--colored-spaces` except `technical`.

<details>
<summary>📸 Compare the styles</summary>

All three are the ground floor of the bundled model, so you can reproduce any of them by
swapping the `--style` and `--colored-spaces` settings.

**Professional** — the default. Rooms share one fill; doors and windows are picked out in
colour.
![Professional floor plan example](assets/professional.png)

**Professional with `--colored-spaces`** — each room type gets its own colour and a legend
entry.
![Coloured floor plan example](assets/professional_colored.png)

**Technical** — outlines only, like a drafting sheet.
![Technical floor plan example](assets/technical.png)

</details>

## Troubleshooting

**`can't open file 'extract_floor_plans.py'` or `ModuleNotFoundError`**
Use the full path: `python src/ifc2plan/extract_floor_plans.py`, run from the `ifc2plan` folder.

**No images came out**
Add `--formatter image`. On its own, the tool writes CSV only.

**No floor plans at all**
The model needs `IfcBuildingStorey` elements — `--overview` will show you whether it has any.

**Rooms aren't coloured**
You need `--colored-spaces` *and* `--naming-conversion`, and the room names in the model
have to match rows in your CSV.

**It ran out of memory**
A model takes roughly six times its file size in memory, so a 200 MB file wants about
1.2 GB. Do one storey at a time, or use `--max-elements` to cap the work. `--parallel` is
faster but holds one copy of the model per core, so it needs more memory, not less.

**It's taking forever** — see below.

## If a run is slow

Almost always, a handful of elements are responsible. On one real storey, **4 elements out
of 669 took 99% of the time** — over half an hour between them.

ifc2plan names them as it goes and lists them at the end of each storey:

```
   ⏱  4 slow element(s), 309s total:
        157.8s  IfcCovering #462475 '47_GM_waterslag' (26,011 faces)
         86.5s  IfcCovering #504259 '47_GM_waterslag' (26,011 faces)
```

If you don't need those elements, `--max-faces` skips them. On the storey above,
`--max-faces 12000` cut the drawing step from **162 seconds to 5.6** and left out exactly
those four elements.

**Read the report before choosing a number.** Face count only roughly predicts cost: in the
same model a 10,239-face door converted in 0.66 s while a 15,736-face covering took 23 s.
Set the limit too low and you lose geometry without saving time. This is why the option is
off by default — it changes what ends up in your drawing.

<details>
<summary>Which elements does <code>--max-faces</code> actually count?</summary>

Face counts are read from the model's own representation data, covering tessellated bodies
(`IfcPolygonalFaceSet`, `IfcTriangulatedFaceSet`), brep solids (`IfcFacetedBrep` and the
rest of the `IfcManifoldSolidBrep` family), surface models, and mapped items wrapping any
of those.

Anything else counts as zero and is therefore never skipped — an unfamiliar body type makes
the flag do less, never more. Swept solids such as `IfcExtrudedAreaSolid` declare no face
count at all, so they are always converted.

</details>

## Origin

`ifc2plan` began as a fork of [byildiz/BatchPlan](https://github.com/byildiz/BatchPlan)
(MIT licensed) and was renamed after diverging substantially. It is a derivative work and
the original copyright is retained — see [LICENSE](LICENSE).

<details>
<summary>What changed since the fork</summary>

- Derived from [`byildiz/BatchPlan@4958a6f`](https://github.com/byildiz/BatchPlan/commit/4958a6f).
  This repository's history was truncated to its own work, so the original commits are
  **not** in this history — they remain in `byildiz/BatchPlan`. The root commit here
  records the derivation.
- The OpenCASCADE/SWIG geometry pipeline was replaced with a [Trimesh](https://trimsh.org/)
  + [Shapely](https://shapely.readthedocs.io/) engine.
- The original's material/LCA database tooling was removed; this repository is scoped to
  floor plan and geometry extraction.
- The former repository, `datarefinerylab/BatchPlan`, is archived and read-only.

</details>

---

**Built with:** [IfcOpenShell](https://ifcopenshell.org/) • [Trimesh](https://trimsh.org/) • [Shapely](https://shapely.readthedocs.io/)
