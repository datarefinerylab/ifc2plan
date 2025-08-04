import argparse
import glob
from pathlib import Path
import pandas as pd

from geometry_engine import ShapelyTrimeshEngine
from formatters import FloorPlanImageFormatter, FloorWKTFormatter
from ifc_processor import default_filter, process_storeys


def setup_formatters(context, selected_formatters):
    formatters = []
    
    for formatter_name in selected_formatters:
        if formatter_name == "image":
            formatters.append(FloorPlanImageFormatter(context))
        elif formatter_name == "wkt":
            formatters.append(FloorWKTFormatter(context))
    
    return formatters


def process_ifc_file(ifc_path, context):
    """Process a single IFC file"""
    print(f"\n{'='*60}")
    print(f"Processing: {ifc_path}")
    print(f"{'='*60}")
    
    ifc_path = Path(ifc_path)
    output_dir = Path(context["args"].output) / ifc_path.stem
    output_dir.mkdir(parents=True, exist_ok=True)
    
    # Update context for this file
    context["output_dir"] = output_dir
    context["ifc_path"] = ifc_path
    
    try:
        process_storeys(context)
    except Exception as e:
        print(f"Error processing {ifc_path}: {e}")
        import traceback
        traceback.print_exc()


def main():
    """Main function with modernized argument parsing"""
    
    parser = argparse.ArgumentParser(description="Extract floor plans from IFC files")
    parser.add_argument("ifc_paths", help="IFC file path or glob pattern")
    parser.add_argument("--output", default="output", help="Output directory")
    parser.add_argument("--formatter", nargs='+', default=["wkt"], 
                       choices=["image", "wkt"], help="Output formatters (space-separated list)")
    parser.add_argument("--filter", help="Filter expression for IfcOpenShell")
    parser.add_argument("--width", type=int, default=2048, help="Image width")
    parser.add_argument("--height", type=int, default=2048, help="Image height")
    parser.add_argument("--style", choices=["professional", "minimal", "colorful", "technical"], 
                       default="professional", help="Visual style theme")
    parser.add_argument("--max-elements", type=int, default=None, 
                       help="Maximum number of elements to process (for testing large files)")
    parser.add_argument("--skip-failed", action="store_true", 
                       help="Continue processing even if some elements fail")
    parser.add_argument("--tolerance", type=float, default=1e-6, 
                       help="Geometric tolerance")
    
    args = parser.parse_args()
    
    # Setup context
    context = {
        "args": args,
        "engine": ShapelyTrimeshEngine(),
        "filter_fn": default_filter(),
        "filter": args.filter,
        "style": args.style,
        "max_elements": args.max_elements
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
    
    for ifc_path in ifc_paths:
        process_ifc_file(ifc_path, context)
    
    print(f"\n{'='*60}")
    print("Processing complete!")
    print(f"Output saved to: {Path(args.output).absolute()}")


if __name__ == "__main__":
    main()
    