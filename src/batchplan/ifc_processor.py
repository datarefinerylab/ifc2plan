import ifcopenshell
from ifcopenshell.util.element import get_decomposition
from tqdm import tqdm

from geometry_engine import IFCGeometryProcessor


def default_filter():
    """Default filter function - exclude problematic element types"""
    def fn(el):
        # Skip annotations and other non-geometric elements that often cause issues
        skip_types = {
            "IfcAnnotation", "IfcGrid", "IfcGridAxis", 
            "IfcOpeningElement", "IfcVirtualElement", "IfcProjectionElement"
        }
        
        return (el.is_a("IfcProduct") and 
                el.Representation is not None and
                not any(el.is_a(skip_type) for skip_type in skip_types))
    return fn


def get_elements_and_shapes(model, filter_fn=None, filter_expr=None, max_elements=None):
    """
    Extract elements and their geometries from IFC model
    
    Args:
        model: IFC model
        filter_fn: Function to filter elements
        filter_expr: IFC filter expression
        max_elements: Maximum number of elements to process (for testing)
    
    Returns:
        Tuple of (elements, meshes)
    """
    processor = IFCGeometryProcessor()
    
    # Get elements to process
    if filter_expr and hasattr(model, 'by_type'):
        from ifcopenshell.util.selector import filter_elements
        elements = filter_elements(model, filter_expr)
    else:
        elements = model.by_type("IfcProduct")
    
    # Filter elements
    if filter_fn:
        elements = [el for el in elements if filter_fn(el)]
    
    # Limit elements for testing large files
    if max_elements and len(elements) > max_elements:
        print(f"🔄 Limiting to first {max_elements} elements for testing")
        elements = elements[:max_elements]
    
    print(f"🔄 Processing {len(elements)} filtered elements...")
    
    # Convert to meshes with progress tracking
    valid_elements = []
    meshes = []
    failed_count = 0
    skipped_count = 0
    
    # Create progress bar
    progress_bar = tqdm(elements, desc="Converting elements", 
                       bar_format='{l_bar}{bar}| {n_fmt}/{total_fmt} [{elapsed}<{remaining}] {postfix}')
    
    for i, element in enumerate(progress_bar):
        if element.Representation is None:
            skipped_count += 1
            continue
            
        mesh = processor.process_ifc_element(element, model)
        if mesh is not None:
            valid_elements.append(element)
            meshes.append(mesh)
        else:
            failed_count += 1
        
        # Update progress bar with statistics
        processed = i + 1
        success_rate = (len(valid_elements) / processed) * 100 if processed > 0 else 0
        progress_bar.set_postfix({
            'Valid': len(valid_elements),
            'Failed': failed_count,
            'Skipped': skipped_count,
            'Success': f'{success_rate:.1f}%'
        })
    
    print(f"\n✅ Processing complete!")
    print(f"   📊 Total processed: {len(elements)}")
    print(f"   ✅ Valid geometries: {len(valid_elements)} ({(len(valid_elements)/len(elements)*100):.1f}%)")
    print(f"   ❌ Failed conversions: {failed_count} ({(failed_count/len(elements)*100):.1f}%)")
    print(f"   ⏭️  Skipped (no representation): {skipped_count} ({(skipped_count/len(elements)*100):.1f}%)")
    
    return valid_elements, meshes


def process_storeys(context):
    """Process floor plans using IfcBuildingStorey elements"""
    
    model = ifcopenshell.open(context["ifc_path"])
    print("Loading and filtering elements...")
    
    elements, meshes = get_elements_and_shapes(
        model, 
        filter_fn=context.get("filter_fn"),
        max_elements=context.get("max_elements")
    )
    
    print(f"Loaded {len(elements)} elements with valid geometry")
    
    processor = IFCGeometryProcessor(context['engine'])
    
    # Process each storey
    storeys = list(model.by_type("IfcBuildingStorey"))
    
    for s0, s1 in zip(storeys[:-1], storeys[1:]):
        name = s0.Name or f"Level_{s0.id()}"
        # Middle height between storeys (convert from mm to m)
        section_height = (s0.Elevation + s1.Elevation) / 2000
        
        print(f"Processing storey: {name} at height {section_height:.2f}m")
        
        # Get elements in this storey
        storey_elements = get_decomposition(s0)
        storey_element_ids = {el.id() for el in storey_elements}
        
        # Filter our loaded elements to this storey
        level_polygons = []
        
        for element, mesh in zip(elements, meshes):
            if element.id() in storey_element_ids:
                # Intersect with plane
                polygons = processor.engine.intersect_with_plane(
                    mesh,
                    plane_origin=(0, 0, section_height),
                    plane_normal=(0, 0, 1)
                )
                
                for poly in polygons:
                    level_polygons.append((
                        element.is_a(),
                        element.Name or f"{element.is_a()}_{element.id()}",
                        poly
                    ))
        
        if level_polygons:
            print(f"  Found {len(level_polygons)} intersections")
            
            # Run formatters
            for formatter in context["formatters"]:
                formatter.process(name, storey_elements, level_polygons)
