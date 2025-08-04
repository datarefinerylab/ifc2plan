import pandas as pd
from typing import List, Tuple

import matplotlib.pyplot as plt
import matplotlib.patches as patches
from shapely.geometry import Polygon, MultiPolygon
from shapely import to_wkt

from geometry_engine import create_geometry_engine


class Formatter:
    """Base class for formatters (headless)"""
    
    def __init__(self, context):
        self.context = context
        self.engine = context.get('engine', create_geometry_engine())
    
    def process(self, name: str, elements: list, polygons: List[Polygon]):
        """Process a floor level - to be implemented by subclasses"""
        raise NotImplementedError()


class FloorPlanImageFormatter(Formatter):
    """Generate floor plan images using matplotlib (headless)"""
    
    def __init__(self, context):
        super().__init__(context)
        style = context.get('style', 'professional')
        
        if style == 'professional':
            self._setup_professional_style()
        elif style == 'minimal':
            self._setup_minimal_style()
        elif style == 'colorful':
            self._setup_colorful_style()
        elif style == 'technical':
            self._setup_technical_style()
    
    def _setup_professional_style(self):
        """Professional architectural color scheme"""
        self.colors = {
            'IfcWall': '#2C3E50',           # Dark blue-gray for walls
            'IfcWallStandardCase': '#2C3E50',
            'IfcSlab': '#ECF0F1',           # Light gray for slabs/floors
            'IfcColumn': '#34495E',         # Darker gray for columns
            'IfcBeam': '#8B4513',           # Brown for beams
            'IfcDoor': '#E67E22',           # Orange for doors
            'IfcWindow': '#3498DB',         # Blue for windows
            'IfcStair': '#9B59B6',          # Purple for stairs
            'IfcStairFlight': '#9B59B6',
            'IfcRailing': '#95A5A6',        # Medium gray for railings
            'IfcRamp': '#F39C12',           # Yellow for ramps
            'IfcFurnishingElement': '#16A085', # Teal for furniture
            'IfcBuildingElementProxy': '#7F8C8D', # Gray for proxies
            'IfcCovering': '#D5DBDB',       # Very light gray for coverings
            'IfcFlowTerminal': '#E74C3C',   # Red for MEP terminals
            'IfcDistributionElement': '#C0392B', # Dark red for MEP
            'IfcSpace': '#F8F9FA',          # Almost white for spaces
            'IfcZone': '#F1C40F',           # Yellow for zones
        }
        self.line_weights = {
            'IfcWall': 2.0, 'IfcWallStandardCase': 2.0, 'IfcSlab': 0.5,
            'IfcColumn': 2.0, 'IfcBeam': 1.5, 'IfcDoor': 1.0, 'IfcWindow': 1.0,
            'IfcStair': 1.5, 'IfcStairFlight': 1.5, 'IfcRailing': 0.8, 'default': 0.5
        }
        self.alphas = {
            'IfcWall': 0.9, 'IfcWallStandardCase': 0.9, 'IfcSlab': 0.3,
            'IfcColumn': 0.9, 'IfcBeam': 0.8, 'IfcDoor': 0.8, 'IfcWindow': 0.7,
            'IfcStair': 0.8, 'IfcSpace': 0.1, 'default': 0.7
        }
    
    def _setup_minimal_style(self):
        """Clean minimal black and white style"""
        base_color = '#2C3E50'
        light_color = '#ECF0F1'
        
        self.colors = {
            'IfcWall': base_color, 'IfcWallStandardCase': base_color,
            'IfcSlab': light_color, 'IfcColumn': base_color, 'IfcBeam': base_color,
            'IfcDoor': '#95A5A6', 'IfcWindow': '#BDC3C7', 'IfcStair': base_color,
            'IfcStairFlight': base_color, 'IfcRailing': '#95A5A6'
        }
        self.line_weights = {k: 1.0 for k in self.colors.keys()}
        self.line_weights['default'] = 1.0
        self.alphas = {k: 0.8 for k in self.colors.keys()}
        self.alphas['IfcSlab'] = 0.2
        self.alphas['default'] = 0.8
    
    def _setup_colorful_style(self):
        """Bright, colorful style for presentations"""
        self.colors = {
            'IfcWall': '#FF6B6B',           # Bright red
            'IfcWallStandardCase': '#FF6B6B',
            'IfcSlab': '#FFE66D',           # Bright yellow
            'IfcColumn': '#4ECDC4',         # Turquoise
            'IfcBeam': '#45B7D1',           # Sky blue
            'IfcDoor': '#FFA07A',           # Light salmon
            'IfcWindow': '#98D8E8',         # Light blue
            'IfcStair': '#DDA0DD',          # Plum
            'IfcStairFlight': '#DDA0DD',
            'IfcRailing': '#F0E68C',        # Khaki
            'IfcRamp': '#FFB347',           # Peach
            'IfcFurnishingElement': '#90EE90', # Light green
            'IfcSpace': '#F0F8FF',          # Alice blue
        }
        self.line_weights = {k: 1.5 for k in self.colors.keys()}
        self.line_weights['default'] = 1.5
        self.alphas = {k: 0.7 for k in self.colors.keys()}
        self.alphas['IfcSlab'] = 0.4
        self.alphas['IfcSpace'] = 0.1
        self.alphas['default'] = 0.7
    
    def _setup_technical_style(self):
        """Technical architectural drawing style - line only, no fills"""
        # All elements use black lines, no fills
        self.colors = {k: 'none' for k in [
            'IfcWall', 'IfcWallStandardCase', 'IfcSlab', 'IfcColumn', 'IfcBeam',
            'IfcDoor', 'IfcWindow', 'IfcStair', 'IfcStairFlight', 'IfcRailing',
            'IfcRamp', 'IfcFurnishingElement', 'IfcSpace', 'IfcZone'
        ]}
        
        # Different line weights for hierarchy
        self.line_weights = {
            'IfcWall': 2.0,              # Thick lines for walls
            'IfcWallStandardCase': 2.0,   
            'IfcColumn': 2.0,             # Thick for structure
            'IfcBeam': 1.5,               # Medium for beams
            'IfcSlab': 1.0,               # Medium for slabs
            'IfcDoor': 1.0,               # Medium for openings
            'IfcWindow': 1.0,
            'IfcStair': 1.5,              # Medium for stairs
            'IfcStairFlight': 1.5,
            'IfcRailing': 0.5,            # Thin for details
            'IfcFurnishingElement': 0.5,  # Thin for furniture
            'IfcSpace': 0.3,              # Very thin for spaces
            'default': 1.0
        }
        
        # No transparency for technical drawings
        self.alphas = {k: 0.0 for k in self.colors.keys()}  # 0 = no fill
        self.alphas['default'] = 0.0
        
        # Set edge colors to black for all elements
        self.edge_colors = {k: 'black' for k in self.colors.keys()}
        self.edge_colors['default'] = 'black'
    
    def process(self, name: str, elements: list, polygons: List[Tuple[str, str, Polygon]]):
        """Generate professional floor plan image"""
        
        if not polygons:
            print(f"No polygons for level {name}")
            return
        
        # Create figure with better DPI and size
        plt.style.use('default')  # Reset to clean style
        fig, ax = plt.subplots(1, 1, figsize=(16, 12))
        fig.patch.set_facecolor('white')
        
        # Calculate bounds with better padding
        all_bounds = []
        for elem_type, elem_name, poly in polygons:
            if poly and not poly.is_empty:
                all_bounds.extend(poly.bounds)
        
        if all_bounds:
            min_x, min_y = min(all_bounds[::2]), min(all_bounds[1::2])
            max_x, max_y = max(all_bounds[::2]), max(all_bounds[1::2])
            
            # Better padding calculation
            range_x, range_y = max_x - min_x, max_y - min_y
            max_range = max(range_x, range_y)
            padding = max_range * 0.05  # 5% padding
            
            ax.set_xlim(min_x - padding, max_x + padding)
            ax.set_ylim(min_y - padding, max_y + padding)
        
        # Group polygons by type for better rendering order
        polygon_groups = {}
        for elem_type, elem_name, poly in polygons:
            if elem_type not in polygon_groups:
                polygon_groups[elem_type] = []
            polygon_groups[elem_type].append((elem_name, poly))
        
        # Render in specific order (background to foreground)
        render_order = [
            'IfcSpace', 'IfcZone', 'IfcSlab', 'IfcCovering',  # Background elements
            'IfcWall', 'IfcWallStandardCase', 'IfcColumn',     # Structure
            'IfcBeam', 'IfcStair', 'IfcStairFlight', 'IfcRamp', # Major elements
            'IfcDoor', 'IfcWindow',                            # Openings
            'IfcRailing', 'IfcFurnishingElement',              # Details
            'IfcFlowTerminal', 'IfcDistributionElement'        # MEP
        ]
        
        # Add any types not in the order to the end
        all_types = set(polygon_groups.keys())
        for elem_type in all_types:
            if elem_type not in render_order:
                render_order.append(elem_type)
        
        # Draw polygons in order
        for elem_type in render_order:
            if elem_type not in polygon_groups:
                continue
                
            color = self.colors.get(elem_type, '#95A5A6')  # Default gray
            alpha = self.alphas.get(elem_type, self.alphas['default'])
            line_weight = self.line_weights.get(elem_type, self.line_weights['default'])
            
            for elem_name, poly in polygon_groups[elem_type]:
                if poly is None or poly.is_empty:
                    continue
                
                # Determine edge color and fill behavior
                if hasattr(self, 'edge_colors'):  # Technical style
                    edge_color = self.edge_colors.get(elem_type, self.edge_colors['default'])
                    fill_color = 'none'  # No fill for technical drawings
                    alpha = 0.0
                else:
                    edge_color = self._darken_color(color) if elem_type != 'IfcWall' else 'black'
                    fill_color = color
                
                if isinstance(poly, Polygon):
                    self._draw_polygon(ax, poly, fill_color, alpha, edge_color, line_weight)
                elif isinstance(poly, MultiPolygon):
                    for p in poly.geoms:
                        self._draw_polygon(ax, p, fill_color, alpha, edge_color, line_weight)
        
        # Enhanced styling
        ax.set_aspect('equal')
        
        # Professional grid
        ax.grid(True, alpha=0.2, linestyle='-', linewidth=0.5, color='gray')
        ax.set_axisbelow(True)
        
        # Clean, professional title
        ax.set_title(f'Floor Plan - {name}', 
                    fontsize=20, fontweight='bold', pad=20,
                    fontfamily='sans-serif')
        
        # Axis labels with units
        ax.set_xlabel('Distance (m)', fontsize=14, fontweight='medium')
        ax.set_ylabel('Distance (m)', fontsize=14, fontweight='medium')
        
        # Better tick formatting
        ax.tick_params(axis='both', which='major', labelsize=11)
        
        # Create professional legend
        self._create_legend(ax, polygon_groups)
        
        # Add scale indicator
        self._add_scale_indicator(ax, all_bounds)
        
        # Add north arrow (if space allows)
        self._add_north_arrow(ax)
        
        # Tight layout with better spacing
        plt.tight_layout(pad=2.0)
        
        # Save with high quality
        output_path = self.context["output_dir"] / f"{name}_floor_plan.png"
        plt.savefig(output_path, dpi=300, bbox_inches='tight', 
                   facecolor='white', edgecolor='none')
        plt.close()
        
        print(f"Saved professional floor plan: {output_path}")
    
    def _draw_polygon(self, ax, poly, color, alpha, edge_color, line_weight):
        """Draw a single polygon with proper styling"""
        
        # Handle technical style (line-only drawing)
        if color == 'none' or alpha == 0.0:
            # Draw only the outline
            x, y = poly.exterior.xy
            ax.plot(x, y, color=edge_color, linewidth=line_weight, solid_capstyle='round')
            
            # Draw holes as lines
            for interior in poly.interiors:
                x, y = interior.xy
                ax.plot(x, y, color=edge_color, linewidth=line_weight*0.7, solid_capstyle='round')
        else:
            # Draw filled polygon (other styles)
            x, y = poly.exterior.xy
            ax.fill(x, y, color=color, alpha=alpha, edgecolor=edge_color, 
                   linewidth=line_weight, zorder=1)
            
            # Holes (if any)
            for interior in poly.interiors:
                x, y = interior.xy
                ax.fill(x, y, color='white', alpha=0.9, edgecolor=edge_color, 
                       linewidth=line_weight*0.7, zorder=2)
    
    def _darken_color(self, color_hex, factor=0.7):
        """Darken a hex color for edge rendering"""
        import matplotlib.colors as mcolors
        try:
            rgb = mcolors.hex2color(color_hex)
            darkened = tuple(c * factor for c in rgb)
            return mcolors.rgb2hex(darkened)
        except:
            return 'black'
    
    def _create_legend(self, ax, polygon_groups):
        """Create a professional legend"""
        # Only show legend for types that are actually present
        present_types = list(polygon_groups.keys())
        
        if len(present_types) > 12:  # Too many for readable legend
            return
        
        # Skip legend for technical style (line-only drawings)
        if hasattr(self, 'edge_colors'):
            return
            
        legend_elements = []
        legend_labels = []
        
        for elem_type in present_types:
            if elem_type in self.colors:
                color = self.colors[elem_type]
                alpha = self.alphas.get(elem_type, self.alphas['default'])
                
                # Create legend patch
                patch = patches.Rectangle((0,0), 1, 1, 
                                        facecolor=color, alpha=alpha,
                                        edgecolor=self._darken_color(color),
                                        linewidth=1)
                legend_elements.append(patch)
                
                # Clean up label
                clean_label = elem_type.replace('Ifc', '').replace('StandardCase', '')
                legend_labels.append(clean_label)
        
        if legend_elements:
            legend = ax.legend(legend_elements, legend_labels, 
                             loc='upper left', bbox_to_anchor=(1.02, 1),
                             frameon=True, fancybox=True, shadow=True,
                             fontsize=10, title='Elements',
                             title_fontsize=12)
            legend.get_frame().set_facecolor('white')
            legend.get_frame().set_alpha(0.9)
    
    def _add_scale_indicator(self, ax, bounds):
        """Add a scale indicator to the plot"""
        if not bounds:
            return
            
        # Calculate appropriate scale length
        range_x = max(bounds[::2]) - min(bounds[::2])
        
        # Choose nice round number for scale
        if range_x > 50:
            scale_length = 10
        elif range_x > 20:
            scale_length = 5
        elif range_x > 10:
            scale_length = 2
        else:
            scale_length = 1
        
        # Position in bottom right
        xlim = ax.get_xlim()
        ylim = ax.get_ylim()
        
        scale_x = xlim[1] - (xlim[1] - xlim[0]) * 0.15
        scale_y = ylim[0] + (ylim[1] - ylim[0]) * 0.05
        
        # Draw scale line
        ax.plot([scale_x - scale_length, scale_x], [scale_y, scale_y], 
               'k-', linewidth=3, solid_capstyle='butt')
        
        # Add scale text
        ax.text(scale_x - scale_length/2, scale_y + (ylim[1] - ylim[0]) * 0.02, 
               f'{scale_length}m', ha='center', va='bottom', 
               fontsize=10, fontweight='bold',
               bbox=dict(boxstyle="round,pad=0.3", facecolor='white', alpha=0.8))
    
    def _add_north_arrow(self, ax):
        """Add a simple north arrow"""
        xlim = ax.get_xlim()
        ylim = ax.get_ylim()
        
        # Position in top right
        arrow_x = xlim[1] - (xlim[1] - xlim[0]) * 0.05
        arrow_y = ylim[1] - (ylim[1] - ylim[0]) * 0.05
        
        # Simple north arrow
        ax.annotate('N', xy=(arrow_x, arrow_y), xytext=(arrow_x, arrow_y - (ylim[1] - ylim[0]) * 0.03),
                   arrowprops=dict(arrowstyle='->', lw=2, color='black'),
                   fontsize=12, fontweight='bold', ha='center')


class FloorWKTFormatter(Formatter):
    """Export floor plans as WKT (Well-Known Text) CSV files"""
    
    def process(self, name: str, elements: list, polygons: List[Tuple[str, str, Polygon]]):
        """Export polygons as WKT"""
        
        data = {"type": [], "name": [], "geometry": []}
        
        for elem_type, elem_name, poly in polygons:
            if poly is None or poly.is_empty:
                continue
                
            wkt = to_wkt(poly)
            data["geometry"].append(wkt)
            data["type"].append(elem_type)
            data["name"].append(elem_name)
        
        if data["type"]:
            df = pd.DataFrame(data)
            output_path = self.context["output_dir"] / f"{name}_floor_plan.csv"
            df.to_csv(output_path, index=False)
            print(f"Saved WKT data: {output_path} ({len(data['type'])} elements)")
    