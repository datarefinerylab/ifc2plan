import argparse
import glob
import sys
from pathlib import Path
import pandas as pd

from geometry_engine import ShapelyTrimeshEngine, SLOW_ELEMENT_SECONDS
from formatters import FloorPlanImageFormatter, FloorWKTFormatter
from ifc_processor import (
    default_filter,
    space_filter,
    process_storeys,
    process_storeys_space_only,
    print_ifc_overview,
    StoreySelectionError,
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


def print_run_plan(args, ifc_paths, selected_formatters):
    """
    Say what this run is about to do, before it does it.

    This replaces a banner that announced three optimisations that are always
    on and are not options - the most prominent thing on screen carried no
    information. These lines are all things the user chose and can change.
    """
    if len(ifc_paths) == 1:
        model = Path(ifc_paths[0]).name
    else:
        model = f"{len(ifc_paths)} files matching {args.ifc_paths!r}"

    storeys = "all" if args.storey is None else str(args.storey)
    elements = "IfcSpace only (rooms)" if args.space_only else "all element types"
    outputs = ", ".join(selected_formatters)
    if "image" in selected_formatters:
        outputs += f" ({args.style}"
        outputs += ", coloured + b&w)" if args.both else (
            ", coloured)" if args.colored_spaces else ", black & white)")

    print()
    print(f"  model      {model}")
    print(f"  storeys    {storeys}")
    print(f"  elements   {elements}")
    print(f"  writing    {outputs}")
    print(f"  cut at     {args.section_offset:g} m above each storey elevation")
    print(f"  output     {Path(args.output).absolute()}")
    if args.max_elements:
        print(f"  note       stopping after {args.max_elements} elements per storey")


def print_written_files(written_files, output_root):
    """List everything the run produced, as paths relative to the output root."""
    print(f"\n{'─' * 66}")

    if not written_files:
        print("Finished, but nothing was written.")
        print("  Check the warnings above: the cutting plane may have missed the")
        print("  geometry, or the storey selection may have matched empty storeys.")
        return

    root = output_root.absolute()
    print(f"Finished - {len(written_files)} file(s) in {root}")
    for path in written_files:
        try:
            display = Path(path).absolute().relative_to(root)
        except ValueError:
            display = Path(path)
        print(f"  {display}")


def process_ifc_file(ifc_path, context):
    """Process a single IFC file"""
    print(f"\n{'═' * 66}")
    print(f"{ifc_path}")
    print(f"{'═' * 66}")

    ifc_path = Path(ifc_path)
    output_dir = Path(context["args"].output) / ifc_path.stem
    output_dir.mkdir(parents=True, exist_ok=True)

    # Update context for this file
    context["output_dir"] = output_dir
    context["ifc_path"] = ifc_path

    try:
        # Choose processing mode
        # Which mode is running is already stated in the run plan above.
        if context["args"].space_only:
            process_storeys_space_only(context)
        else:
            process_storeys(context)
    except StoreySelectionError:
        # The user asked for storeys that do not exist. That is not a per-file
        # processing failure to log and move past - the whole run is wrong.
        raise
    except Exception as e:
        print(f"Error processing {ifc_path}: {e}")
        import traceback
        traceback.print_exc()


def main():
    """Main function with modernized argument parsing"""

    parser = argparse.ArgumentParser(
        description="Extract 2D floor plans (PNG / WKT CSV) from IFC building models.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Start here:
  # 1. See what is in the model - storeys, their indices and elevations
  python src/ifc2plan/extract_floor_plans.py "examples/data/Shependomlaan/IFC Schependomlaan.ifc" --overview

  # 2. Cut one storey and look at it
  python src/ifc2plan/extract_floor_plans.py "examples/data/Shependomlaan/IFC Schependomlaan.ifc" \\
      -s 1 -f image wkt -o output

  # 3. Cut the whole building
  python src/ifc2plan/extract_floor_plans.py "examples/data/Shependomlaan/IFC Schependomlaan.ifc" \\
      -s all -f image wkt -o output

Selecting storeys (-s/--storey):
  -s 1            one storey, by index from --overview
  -s 0,2          several
  -s 1-3          an inclusive range
  -s begane       any storey whose name contains this text
  -s all          every storey (the default)

Rooms only, with English room names and colour:
  python src/ifc2plan/extract_floor_plans.py "examples/data/Shependomlaan/IFC Schependomlaan.ifc" \\
      --space-only --naming-conversion naming_conversion.csv --colored-spaces -f image

Run this script by its path, as above - it is not installed as a command.
        """
    )

    parser.add_argument("ifc_paths", metavar="IFC_PATH",
                        help="IFC file, or a glob pattern matching several")

    common = parser.add_argument_group(
        "common options",
        "The four you normally touch.")
    common.add_argument("-o", "--output", default="output", metavar="DIR",
                        help="Where to write results (default: output). Each model "
                             "gets its own subdirectory.")
    common.add_argument("-s", "--storey", default=None, metavar="SPEC",
                        help="Which storeys to cut: an index (1), a list (0,2), a "
                             "range (1-3), part of a storey name (begane), or 'all'. "
                             "Default: all. Run --overview to see the choices.")
    common.add_argument("-f", "--formatter", nargs='+', default=["wkt"],
                        choices=["image", "wkt"], metavar="{image,wkt}",
                        help="What to write: 'image' for a PNG plan, 'wkt' for a CSV "
                             "of geometries, or both (default: wkt)")
    common.add_argument("--overview", action="store_true",
                        help="Print the model's storeys and element counts, then exit "
                             "without cutting anything")

    what = parser.add_argument_group(
        "what to extract",
        "Which elements end up in the plan, and where the cut is taken.")
    what.add_argument("--space-only", action="store_true",
                      help="Extract only IfcSpace elements - rooms, no walls")
    what.add_argument("--section-offset", type=float, default=1.5, metavar="METRES",
                      help="Height of the cutting plane above each storey's elevation, "
                           "in metres (default: 1.5, the conventional plan cut height). "
                           "Storeys whose geometry does not reach this plane fall back "
                           "to a height that does; the run reports when that happens.")
    what.add_argument("--naming-conversion", type=str, default=None, metavar="CSV",
                      help="CSV mapping room names to English. Format: original,english")
    what.add_argument("--filter", help="Filter expression for IfcOpenShell")

    look = parser.add_argument_group(
        "how the image looks",
        "Ignored unless -f includes 'image'.")
    look.add_argument("--style", choices=["professional", "minimal", "colorful", "technical"],
                      default="professional", help="Visual style theme (default: professional)")
    look.add_argument("--colored-spaces", action="store_true",
                      help="Colour rooms by type (default: black & white)")
    look.add_argument("--both", action="store_true",
                      help="Write both the coloured and the black & white version")
    look.add_argument("--width", type=int, default=2048, help="Image width in pixels")
    look.add_argument("--height", type=int, default=2048, help="Image height in pixels")

    speed = parser.add_argument_group(
        "speed and troubleshooting",
        "Reach for these on large models or when a run misbehaves.")
    speed.add_argument("--parallel", action="store_true",
                       help="Convert element geometry across multiple cores. Each worker "
                            "holds its own copy of the model, so the pool is sized against "
                            "available memory as well as core count")
    speed.add_argument("--max-elements", type=int, default=None,
                       help="Stop after this many elements per storey (for trying things out)")
    speed.add_argument("--skip-failed", action="store_true",
                       help="Continue processing even if some elements fail")
    speed.add_argument("--slow-element-seconds", type=float, default=SLOW_ELEMENT_SECONDS,
                       help=f"Report any element taking longer than this to convert "
                            f"(default: {SLOW_ELEMENT_SECONDS})")
    speed.add_argument("--max-faces", type=int, default=None,
                       help="Skip elements whose representation declares more faces than this. "
                            "Off by default: it trades completeness for speed, and a handful of "
                            "highly tessellated elements can be most of a run's time")
    speed.add_argument("--tolerance", type=float, default=1e-6,
                       help="Geometric tolerance")

    args = parser.parse_args()

    # Handle overview mode - just show file info and exit
    if args.overview:
        ifc_paths = glob.glob(args.ifc_paths)
        if not ifc_paths:
            print(f"No IFC files found matching: {args.ifc_paths}")
            return 1

        for ifc_path in ifc_paths:
            print_ifc_overview(ifc_path)

        return 0  # Exit after showing overview

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
        "storey_selection": args.storey,  # index / list / range / name / all
        "written_files": [],
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
        return 1

    print_run_plan(args, ifc_paths, selected_formatters)

    for ifc_path in ifc_paths:
        try:
            process_ifc_file(ifc_path, context)
        except StoreySelectionError as exc:
            print(f"\n❌ {exc}")
            return 2

    print_written_files(context["written_files"], Path(args.output))
    return 0


if __name__ == "__main__":
    sys.exit(main() or 0)
