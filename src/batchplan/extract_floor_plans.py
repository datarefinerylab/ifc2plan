import argparse
import glob
from pathlib import Path
import pandas as pd
import ifcopenshell

from geometry_engine import ShapelyTrimeshEngine, IFCGeometryProcessor
from formatters import FloorPlanImageFormatter, FloorWKTFormatter
from ifc_processor import (
    default_filter,
    space_filter,
    process_storeys,
    process_storeys_space_only
)


def setup_formatters(context, selected_formatters):
    formatters = []

    for formatter_name in selected_formatters:
        if formatter_name == "image":
            formatters.append(FloorPlanImageFormatter(context))
        elif formatter_name == "wkt":
            formatters.append(FloorWKTFormatter(context))

    return formatters


def load_naming_conversion(csv_path):
    """Load naming conversion from CSV file"""
    try:
        df = pd.read_csv(csv_path)
        # Assume CSV has columns: 'original', 'english' or first two columns
        if len(df.columns) >= 2:
            return dict(zip(df.iloc[:, 0], df.iloc[:, 1]))
        else:
            print(f"Warning: CSV must have at least 2 columns")
            return {}
    except Exception as e:
        print(f"Warning: Could not load naming conversion from {csv_path}: {e}")
        return {}


def show_ifc_overview(ifc_path):
    """Show overview of IFC file and exit"""
    ifc_file = ifcopenshell.open(ifc_path)
    processor = IFCGeometryProcessor()
    processor.print_ifc_overview(ifc_file)


def process_ifc_file(ifc_path, context):
    """Process a single IFC file"""
    print(f"\n{'=' * 60}")
    print(f"Processing: {ifc_path}")
    print(f"{'=' * 60}")

    ifc_path = Path(ifc_path)
    output_dir = Path(context["args"].output) / ifc_path.stem
    output_dir.mkdir(parents=True, exist_ok=True)

    # Update context for this file
    context["output_dir"] = output_dir
    context["ifc_path"] = ifc_path

    # Add storey index to context if specified
    if hasattr(context["args"], "storey") and context["args"].storey is not None:
        context["storey_index"] = context["args"].storey

    try:
        # Choose processing mode
        if context["args"].space_only:
            print("Mode: Space-only extraction")
            process_storeys_space_only(context)
        else:
            print("Mode: Full geometry extraction (all elements)")
            process_storeys(context)
    except Exception as e:
        print(f"Error processing {ifc_path}: {e}")
        import traceback
        traceback.print_exc()


def main():
    """Main function with modernized argument parsing"""

    parser = argparse.ArgumentParser(
        description="Extract floor plans from IFC files",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Show overview of IFC file (storeys, elements, etc.)
  python extract_floor_plans.py building.ifc --overview

  # Extract all elements (walls, spaces, etc.) - default: professional b&w style
  python extract_floor_plans.py building.ifc --output ./output

  # Extract only a specific storey (use --overview first to see storey indices)
  python extract_floor_plans.py building.ifc --storey 0 --output ./output

  # Extract only IfcSpace elements with colored room types
  python extract_floor_plans.py building.ifc --space-only --naming-conversion names.csv --colored-spaces

  # Generate both colored and black & white versions
  python extract_floor_plans.py building.ifc --space-only --naming-conversion names.csv --both
        """
    )

    parser.add_argument("ifc_paths", help="IFC file path or glob pattern")
    parser.add_argument("--output", default="output", help="Output directory")
    parser.add_argument("--formatter", nargs='+', default=["wkt"],
                        choices=["image", "wkt"],
                        help="Output formatters (space-separated list)")

    # Overview mode
    parser.add_argument("--overview", action="store_true",
                        help="Show IFC file overview (storeys, elements, structure) and exit")

    # Processing mode
    parser.add_argument("--space-only", action="store_true",
                        help="Extract only IfcSpace elements (matches notebook approach)")
    parser.add_argument("--storey", type=int, default=None,
                        help="Process only specific storey by index (0-based). Use --overview to see available storeys")
    parser.add_argument("--naming-conversion", type=str, default=None,
                        help="CSV file with naming conversion (Dutch->English). Format: original,english")

    # Filtering
    parser.add_argument("--filter", help="Filter expression for IfcOpenShell")

    # Visualization
    parser.add_argument("--width", type=int, default=2048, help="Image width")
    parser.add_argument("--height", type=int, default=2048, help="Image height")
    parser.add_argument("--style", choices=["professional", "minimal", "colorful", "technical"],
                        default="professional", help="Visual style theme")
    parser.add_argument("--colored-spaces", action="store_true",
                        help="Color spaces by room type (default: black & white)")
    parser.add_argument("--both", action="store_true",
                        help="Generate both colored and black & white versions")

    # Performance
    parser.add_argument("--max-elements", type=int, default=None,
                        help="Maximum number of elements to process (for testing large files)")
    parser.add_argument("--skip-failed", action="store_true",
                        help="Continue processing even if some elements fail")
    parser.add_argument("--tolerance", type=float, default=1e-6,
                        help="Geometric tolerance")

    args = parser.parse_args()

    # Process IFC files
    ifc_paths = glob.glob(args.ifc_paths)
    if not ifc_paths:
        print(f"No IFC files found matching: {args.ifc_paths}")
        return

    # Handle overview mode
    if args.overview:
        for ifc_path in ifc_paths:
            show_ifc_overview(ifc_path)
        return

    # Load naming conversion if provided
    naming_conversion = {}
    if args.naming_conversion:
        naming_conversion = load_naming_conversion(args.naming_conversion)
        print(f"Loaded {len(naming_conversion)} naming conversions")

    # Setup context
    context = {
        "args": args,
        "engine": ShapelyTrimeshEngine(),
        "filter_fn": space_filter() if args.space_only else default_filter(),
        "filter": args.filter,
        "style": args.style,
        "max_elements": args.max_elements,
        "naming_conversion": naming_conversion,
        "colored_spaces": args.colored_spaces,
        "both": args.both
    }

    # Setup formatters
    if not args.formatter:
        selected_formatters = ["image", "wkt"]
    else:
        selected_formatters = args.formatter

    context["formatters"] = setup_formatters(context, selected_formatters)

    # Process IFC files
    for ifc_path in ifc_paths:
        process_ifc_file(ifc_path, context)

    print(f"\n{'=' * 60}")
    print("Processing complete!")
    print(f"Output saved to: {Path(args.output).absolute()}")


if __name__ == "__main__":
    main()
