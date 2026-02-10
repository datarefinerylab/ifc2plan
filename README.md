# IFC Floor Plan Extractor

[![Python 3.8+](https://img.shields.io/badge/python-3.8+-blue.svg)](https://www.python.org/downloads/)
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
🔍 **IFC file overview** - inspect storeys and elements before processing
🏢 **Storey-specific extraction** - process individual floors by index  

## Quick Start

```bash
# Install dependencies
pip install -r requirements.txt

# Inspect IFC file structure (storeys, elements, etc.)
python extract_floor_plans.py building.ifc --overview

# Extract geometric data as CSV/WKT
python extract_floor_plans.py building.ifc

# Process only a specific storey (e.g., ground floor)
python extract_floor_plans.py building.ifc --storey 0

# Generate professional floor plan images with colored room types
python extract_floor_plans.py building.ifc --formatter image wkt --colored-spaces --naming-conversion naming_conversion.csv

# Extract only spaces with room type coloring
python extract_floor_plans.py building.ifc --space-only --colored-spaces --naming-conversion naming_conversion.csv
```

## Installation

**Requirements:** Python 3.8+

```bash
git clone https://github.com/datarefinerylab/BatchPlan.git
cd BatchPlan
pip install -r requirements.txt
```

## Usage

### Inspecting IFC Files

Before processing, inspect the IFC file structure to understand its contents:

```bash
# Show overview: storeys, elements, spatial structure
python extract_floor_plans.py building.ifc --overview
```

**Example output:**
```
============================================================
IFC FILE OVERVIEW
============================================================
Project: Office Building
Building: Main Building
Schema: IFC2X3

Total Storeys: 3
Total Elements: 1247

Element Types (Overall):
  IfcWall: 456
  IfcSpace: 89
  IfcSlab: 67
  ...

Storey Details:

  [0] Ground Floor
      Elevation: 0.00
      Elements: 423
      Element Types:
        IfcWall: 152
        IfcSpace: 28
        ...

  [1] First Floor
      Elevation: 3.50
      Elements: 412
      ...
```

### Basic Extraction

```bash
# Basic usage (default: professional black & white style)
python extract_floor_plans.py input.ifc

# Process only a specific storey by index
python extract_floor_plans.py building.ifc --storey 0 --output ./ground_floor

# Process multiple storeys individually
python extract_floor_plans.py building.ifc --storey 1 --output ./first_floor
python extract_floor_plans.py building.ifc --storey 2 --output ./second_floor

# Extract only spaces with colored room types
python extract_floor_plans.py building.ifc \
  --space-only \
  --colored-spaces \
  --naming-conversion naming_conversion.csv

# Generate both colored and black & white versions
python extract_floor_plans.py building.ifc \
  --both \
  --naming-conversion naming_conversion.csv

# Multiple outputs and styling
python extract_floor_plans.py building.ifc \
  --output ./plans \
  --formatter image wkt \
  --style colorful \
  --colored-spaces \
  --width 4096

# Batch process multiple files
python extract_floor_plans.py "buildings/*.ifc" --output ./all_plans
```

### Command Line Options

| Option | Description | Default |
|--------|-------------|---------|
| `--overview` | Show IFC file overview (storeys, elements) and exit | `False` |
| `--storey INDEX` | Process only specific storey by index (0-based) | All storeys |
| `--output` | Output directory | `output` |
| `--formatter` | Output format: `image`, `wkt` (space-separated) | `wkt` |
| `--style` | Visual style: `professional`, `minimal`, `colorful`, `technical` | `professional` |
| `--colored-spaces` | Color spaces by room type (requires naming conversion) | `False` |
| `--both` | Generate both colored and black & white versions | `False` |
| `--space-only` | Extract only IfcSpace elements | `False` |
| `--naming-conversion` | CSV file for room name translation (format: `original,english`) | `None` |
| `--width/--height` | Image dimensions (pixels) | `2048` |
| `--max-elements` | Limit for large files (testing) | `None` |

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
python extract_floor_plans.py building.ifc --colored-spaces --naming-conversion naming_conversion.csv
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

**Need to inspect the IFC file first?**
- Use `--overview` to see storey names, indices, and element counts before processing
- This helps identify which storey to extract using `--storey INDEX`

**No floor plans generated?**
- Ensure your IFC file contains `IfcBuildingStorey` elements (check with `--overview`)
- Try `--max-elements 100` for testing large files
- Check that `--formatter image` is specified if you want image outputs

**Want to process only specific floors?**
- First run with `--overview` to see available storey indices
- Then use `--storey 0` (or desired index) to process that specific floor
- Useful for large buildings or when you only need certain floors

**Room types not colored?**
- Ensure you use `--colored-spaces` flag
- Provide a naming conversion CSV with `--naming-conversion`
- Check that room names in IFC match entries in your CSV (case-insensitive)

**AttributeError: 'float' object has no attribute 'lower'?**
- Remove empty rows from your naming conversion CSV file
- Ensure all entries in the CSV have both original and translated names

**Memory issues with large buildings?**
- Use `--storey INDEX` to process one floor at a time
- Use `--max-elements` to limit processing
- Process files individually instead of batch

## License

MIT License - see [LICENSE](LICENSE) file for details.

---

**Built with:** [IfcOpenShell](https://ifcopenshell.org/) • [Trimesh](https://trimsh.org/) • [Shapely](https://shapely.readthedocs.io/)