import argparse
import glob
from pathlib import Path
import pandas as pd

from geometry_engine import ShapelyTrimeshEngine, SLOW_ELEMENT_SECONDS
from formatters import FloorPlanImageFormatter, FloorWKTFormatter
from ifc_processor import (
    default_filter,
    space_filter,
    process_storeys,
    process_storeys_space_only,
    print_ifc_overview
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

    try:
        # Choose processing mode
        if context["args"].space_only:
            print("Mode: Space-only extraction (like notebook)")
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
        description="Extract floor plans from IFC files - OPTIMIZED VERSION",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Show file overview without processing geometry
  python extract_floor_plans.py building.ifc --overview

  # Extract only storey 5 (use --overview to see indices)
  python extract_floor_plans.py building.ifc --storey 5

  # Extract all elements (walls, spaces, etc.) - default: professional b&w style
  python extract_floor_plans.py building.ifc --output ./output

  # Extract only IfcSpace elements with colored room types
  python extract_floor_plans.py building.ifc --space-only --naming-conversion names.csv --colored-spaces

  # Generate both colored and black & white versions for storey 0
  python extract_floor_plans.py building.ifc --storey 0 --space-only --naming-conversion names.csv --both
        """
    )

    parser.add_argument("ifc_paths", help="IFC file path or glob pattern")
    parser.add_argument("--output", default="output", help="Output directory")
    parser.add_argument("--formatter", nargs='+', default=["wkt"],
                        choices=["image", "wkt"],
                        help="Output formatters (space-separated list)")

    # Processing mode
    parser.add_argument("--overview", action="store_true",
                        help="Show IFC file overview (storeys, elements) without processing geometry")
    parser.add_argument("--storey", type=int, default=None,
                        help="Process only specific storey by index (0-based). Use --overview to see indices.")
    parser.add_argument("--section-offset", type=float, default=1.5, metavar="METRES",
                        help="Height of the cutting plane above each storey's elevation, "
                             "in metres (default: 1.5, the conventional plan cut height). "
                             "Storeys whose geometry does not reach this plane fall back "
                             "to a height that does; the run reports when that happens.")
    parser.add_argument("--space-only", action="store_true",
                        help="Extract only IfcSpace elements (matches notebook approach)")
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
    parser.add_argument("--parallel", action="store_true",
                        help="Convert element geometry across multiple cores. Each worker "
                             "holds its own copy of the model, so the pool is sized against "
                             "available memory as well as core count")
    parser.add_argument("--max-elements", type=int, default=None,
                        help="Maximum number of elements to process (for testing large files)")
    parser.add_argument("--skip-failed", action="store_true",
                        help="Continue processing even if some elements fail")
    parser.add_argument("--slow-element-seconds", type=float, default=SLOW_ELEMENT_SECONDS,
                        help=f"Report any element taking longer than this to convert "
                             f"(default: {SLOW_ELEMENT_SECONDS})")
    parser.add_argument("--max-faces", type=int, default=None,
                        help="Skip elements whose representation declares more faces than this. "
                             "Off by default: it trades completeness for speed, and a handful of "
                             "highly tessellated elements can be most of a run's time")
    parser.add_argument("--tolerance", type=float, default=1e-6,
                        help="Geometric tolerance")

    args = parser.parse_args()

    # Handle overview mode - just show file info and exit
    if args.overview:
        ifc_paths = glob.glob(args.ifc_paths)
        if not ifc_paths:
            print(f"No IFC files found matching: {args.ifc_paths}")
            return

        for ifc_path in ifc_paths:
            print_ifc_overview(ifc_path)

        return  # Exit after showing overview

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
        "both": args.both,
        "parallel": args.parallel,  # Opt-in parallel processing
        "storey_index": args.storey,  # Add storey filter
        "section_offset": args.section_offset,
        "slow_seconds": args.slow_element_seconds,
        "max_faces": args.max_faces,
    }

    # Setup formatters
    if not args.formatter:
        selected_formatters = ["image", "wkt"]
    else:
        selected_formatters = args.formatter

    context["formatters"] = setup_formatters(context, selected_formatters)

    # Process IFC files
    ifc_paths = glob.glob(args.ifc_paths)
    if not ifc_paths:
        print(f"No IFC files found matching: {args.ifc_paths}")
        return

    print(f"\n{'=' * 60}")
    print(f"PERFORMANCE OPTIMIZATIONS ENABLED:")
    print(f"  🎯 Storey-filtered processing: ON")
    print(f"  🚀 Fast geometry extraction: ON")
    print(f"  💾 Settings caching: ON")
    if context['storey_index'] is not None:
        print(f"  📍 Single storey mode: Storey {context['storey_index']}")
    print(f"{'=' * 60}\n")

    for ifc_path in ifc_paths:
        process_ifc_file(ifc_path, context)

    print(f"\n{'=' * 60}")
    print("Processing complete!")
    print(f"Output saved to: {Path(args.output).absolute()}")


if __name__ == "__main__":
    main()
