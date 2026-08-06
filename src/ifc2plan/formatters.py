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

    def record_output(self, path, detail=""):
        """
        Note a written file and report it as one short line.

        The run collects these so it can list everything it produced at the
        end; mid-run the absolute path was the longest line on screen and the
        list of them was scattered between storeys.
        """
        self.context.setdefault("written_files", []).append(path)
        print(f"  → {path.name}{detail}")


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
            'IfcWall': '#2C3E50',  # Dark blue-gray for walls
            'IfcWallStandardCase': '#2C3E50',
            'IfcSlab': '#ECF0F1',  # Light gray for slabs/floors
            'IfcColumn': '#34495E',  # Darker gray for columns
            'IfcBeam': '#8B4513',  # Brown for beams
            'IfcDoor': '#E67E22',  # Orange for doors
            'IfcWindow': '#3498DB',  # Blue for windows
            'IfcStair': '#9B59B6',  # Purple for stairs
            'IfcStairFlight': '#9B59B6',
            'IfcRailing': '#95A5A6',  # Medium gray for railings
            'IfcRamp': '#F39C12',  # Yellow for ramps
            'IfcFurnishingElement': '#16A085',  # Teal for furniture
            'IfcBuildingElementProxy': '#7F8C8D',  # Gray for proxies
            'IfcCovering': '#D5DBDB',  # Very light gray for coverings
            'IfcFlowTerminal': '#E74C3C',  # Red for MEP terminals
            'IfcDistributionElement': '#C0392B',  # Dark red for MEP
            'IfcSpace': '#F8F9FA',  # Almost white for spaces
            'IfcZone': '#F1C40F',  # Yellow for zones
        }

        # Room type color palette
        self.room_type_colors = {
            'bedroom': '#FFB6C1',  # Light pink
            'bathroom': '#87CEEB',  # Sky blue
            'livingroom': '#98FB98',  # Pale green
            'study room': '#DDA0DD',  # Plum
            'storage': '#F0E68C',  # Khaki
            'corridor': '#E0E0E0',  # Light gray
            'staircase': '#D8BFD8',  # Thistle
            'elevator': '#B0C4DE',  # Light steel blue
            'elevator shaft': '#B0C4DE',
            'elevator hall': '#AFEEEE',  # Pale turquoise
            'balcony': '#FFDAB9',  # Peach puff
            'terrace': '#FFDAB9',
            'entrance': '#F5DEB3',  # Wheat
            'entrance hall': '#F5DEB3',
            'circulation': '#D3D3D3',  # Light gray
            'bike storage': '#FFE4B5',  # Moccasin
            'service room': '#FAFAD2',  # Light goldenrod
            'general': '#F5F5DC',  # Beige
            'shops': '#FFE4E1',  # Misty rose
            'scooters': '#FFFACD',  # Lemon chiffon
            'shaft': '#C0C0C0',  # Silver
            'server room': '#E6E6FA',  # Lavender
            'inner courtyard': '#F0FFF0',  # Honeydew
            'gallery': '#FFF0F5',  # Lavender blush
            'not defined': '#FFFFFF',  # White
            'area': '#F8F8FF',  # Ghost white
            'room': '#FAF0E6',  # Linen
        }

        self.line_weights = {
            'IfcWall': 2.0, 'IfcWallStandardCase': 2.0, 'IfcSlab': 0.5,
            'IfcColumn': 2.0, 'IfcBeam': 1.5, 'IfcDoor': 1.0, 'IfcWindow': 1.0,
            'IfcStair': 1.5, 'IfcStairFlight': 1.5, 'IfcRailing': 0.8, 'default': 0.5
        }
        self.alphas = {
            'IfcWall': 0.9, 'IfcWallStandardCase': 0.9, 'IfcSlab': 0.3,
            'IfcColumn': 0.9, 'IfcBeam': 0.8, 'IfcDoor': 0.8, 'IfcWindow': 0.7,
            'IfcStair': 0.8, 'IfcSpace': 0.6, 'default': 0.7
        }

    def _setup_minimal_style(self):
        """Clean minimal black and white style"""
        base_color = '#2C3E50'
        light_color = '#ECF0F1'

        self.colors = {
            'IfcWall': base_color, 'IfcWallStandardCase': base_color,
            'IfcSlab': light_color, 'IfcColumn': base_color, 'IfcBeam': base_color,
            'IfcDoor': '#95A5A6', 'IfcWindow': '#BDC3C7', 'IfcStair': base_color,
            'IfcStairFlight': base_color, 'IfcRailing': '#95A5A6', 'IfcSpace': light_color
        }

        # Minimal grayscale room type colors
        self.room_type_colors = {
            'bedroom': '#E8E8E8', 'bathroom': '#D8D8D8', 'livingroom': '#C8C8C8',
            'study room': '#E0E0E0', 'storage': '#F0F0F0', 'corridor': '#D0D0D0',
            'staircase': '#C0C0C0', 'elevator': '#D5D5D5', 'elevator shaft': '#D5D5D5',
            'elevator hall': '#E5E5E5', 'balcony': '#F5F5F5', 'terrace': '#F5F5F5',
            'entrance': '#EBEBEB', 'entrance hall': '#EBEBEB', 'circulation': '#DADADA',
            'bike storage': '#EDEDED', 'service room': '#F2F2F2', 'general': '#F8F8F8',
            'shops': '#E3E3E3', 'scooters': '#F7F7F7', 'shaft': '#CDCDCD',
            'server room': '#E7E7E7', 'inner courtyard': '#FAFAFA', 'gallery': '#F9F9F9',
            'not defined': '#FFFFFF', 'area': '#FCFCFC', 'room': '#F6F6F6',
        }

        self.line_weights = {k: 1.0 for k in self.colors.keys()}
        self.line_weights['default'] = 1.0
        self.alphas = {k: 0.8 for k in self.colors.keys()}
        self.alphas['IfcSlab'] = 0.2
        self.alphas['IfcSpace'] = 0.6
        self.alphas['default'] = 0.8

    def _setup_colorful_style(self):
        """Bright, colorful style for presentations"""
        self.colors = {
            'IfcWall': '#FF6B6B',  # Bright red
            'IfcWallStandardCase': '#FF6B6B',
            'IfcSlab': '#FFE66D',  # Bright yellow
            'IfcColumn': '#4ECDC4',  # Turquoise
            'IfcBeam': '#45B7D1',  # Sky blue
            'IfcDoor': '#FFA07A',  # Light salmon
            'IfcWindow': '#98D8E8',  # Light blue
            'IfcStair': '#DDA0DD',  # Plum
            'IfcStairFlight': '#DDA0DD',
            'IfcRailing': '#F0E68C',  # Khaki
            'IfcRamp': '#FFB347',  # Peach
            'IfcFurnishingElement': '#90EE90',  # Light green
            'IfcSpace': '#F0F8FF',  # Alice blue
        }

        # Vibrant room type colors for colorful style
        self.room_type_colors = {
            'bedroom': '#FFB3E6',  # Bright pink
            'bathroom': '#66D9EF',  # Bright cyan
            'livingroom': '#A6E57A',  # Bright lime green
            'study room': '#E6A8FF',  # Bright lavender
            'storage': '#FFE680',  # Bright yellow
            'corridor': '#E0E0E0',  # Light gray
            'staircase': '#E6B3FF',  # Bright purple
            'elevator': '#99CCFF',  # Bright blue
            'elevator shaft': '#99CCFF',
            'elevator hall': '#80F5F5',  # Bright turquoise
            'balcony': '#FFD9A3',  # Bright peach
            'terrace': '#FFD9A3',
            'entrance': '#FFEAB3',  # Bright cream
            'entrance hall': '#FFEAB3',
            'circulation': '#CCCCCC',  # Gray
            'bike storage': '#FFECB3',  # Bright beige
            'service room': '#FFFFB3',  # Bright lemon
            'general': '#FFFFCC',  # Pale yellow
            'shops': '#FFD6E0',  # Bright rose
            'scooters': '#FFFFCC',  # Pale yellow
            'shaft': '#CCCCCC',  # Gray
            'server room': '#D9B3FF',  # Bright lilac
            'inner courtyard': '#E6FFE6',  # Bright mint
            'gallery': '#FFE6F0',  # Bright blush
            'not defined': '#FFFFFF',  # White
            'area': '#F0F8FF',  # Alice blue
            'room': '#FFF5E6',  # Cream
        }

        self.line_weights = {k: 1.5 for k in self.colors.keys()}
        self.line_weights['default'] = 1.5
        self.alphas = {k: 0.7 for k in self.colors.keys()}
        self.alphas['IfcSlab'] = 0.4
        self.alphas['IfcSpace'] = 0.6
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
            'IfcWall': 2.0,  # Thick lines for walls
            'IfcWallStandardCase': 2.0,
            'IfcColumn': 2.0,  # Thick for structure
            'IfcBeam': 1.5,  # Medium for beams
            'IfcSlab': 1.0,  # Medium for slabs
            'IfcDoor': 1.0,  # Medium for openings
            'IfcWindow': 1.0,
            'IfcStair': 1.5,  # Medium for stairs
            'IfcStairFlight': 1.5,
            'IfcRailing': 0.5,  # Thin for details
            'IfcFurnishingElement': 0.5,  # Thin for furniture
            'IfcSpace': 0.3,  # Very thin for spaces
            'default': 1.0
        }

        # No transparency for technical drawings
        self.alphas = {k: 0.0 for k in self.colors.keys()}  # 0 = no fill
        self.alphas['default'] = 0.0

        # Set edge colors to black for all elements
        self.edge_colors = {k: 'black' for k in self.colors.keys()}
        self.edge_colors['default'] = 'black'

    def process(self, name: str, elements: list, polygons: List[Tuple[str, str, Polygon, str]]):
        """Generate professional floor plan image"""

        if not polygons:
            print(f"No polygons for level {name}")
            return

        # Determine if we should generate both versions
        generate_both = self.context.get('both', False)
        colored_spaces = self.context.get('colored_spaces', False)

        if generate_both:
            # Generate black & white version first
            self._generate_floor_plan(name, elements, polygons, colored_spaces=False, suffix='_bw')
            # Then generate colored version
            self._generate_floor_plan(name, elements, polygons, colored_spaces=True, suffix='_colored')
        else:
            # Generate single version based on colored_spaces flag
            self._generate_floor_plan(name, elements, polygons, colored_spaces=colored_spaces, suffix='')

    def _generate_floor_plan(self, name: str, elements: list, polygons: List[Tuple[str, str, Polygon, str]],
                             colored_spaces: bool = False, suffix: str = ''):
        """Generate a single floor plan image with specified coloring"""

        # Create figure with better DPI and size
        plt.style.use('default')  # Reset to clean style
        fig, ax = plt.subplots(1, 1, figsize=(16, 12))
        fig.patch.set_facecolor('white')

        # Calculate bounds with better padding
        all_bounds = []
        for elem_type, elem_name, poly, room_type, *_ in polygons:
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
        # Also track room types for IfcSpace elements
        polygon_groups = {}
        room_type_groups = {}  # Track unique room types for legend

        for elem_type, elem_name, poly, room_type, *_ in polygons:
            if elem_type not in polygon_groups:
                polygon_groups[elem_type] = []
            polygon_groups[elem_type].append((elem_name, poly, room_type))

            # Track room types for IfcSpace elements
            if elem_type == 'IfcSpace' and room_type:
                if room_type not in room_type_groups:
                    room_type_groups[room_type] = []
                room_type_groups[room_type].append((elem_name, poly))

        # Render in specific order (background to foreground)
        render_order = [
            'IfcSpace', 'IfcZone', 'IfcSlab', 'IfcCovering',  # Background elements
            'IfcWall', 'IfcWallStandardCase', 'IfcColumn',  # Structure
            'IfcBeam', 'IfcStair', 'IfcStairFlight', 'IfcRamp',  # Major elements
            'IfcDoor', 'IfcWindow',  # Openings
            'IfcRailing', 'IfcFurnishingElement',  # Details
            'IfcFlowTerminal', 'IfcDistributionElement'  # MEP
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

            for elem_name, poly, room_type in polygon_groups[elem_type]:
                if poly is None or poly.is_empty:
                    continue

                # Determine edge color and fill behavior
                if hasattr(self, 'edge_colors'):  # Technical style
                    edge_color = self.edge_colors.get(elem_type, self.edge_colors['default'])
                    fill_color = 'none'  # No fill for technical drawings
                    alpha = 0.0
                else:
                    # Use room type color for IfcSpace elements only if colored_spaces is enabled
                    if elem_type == 'IfcSpace' and room_type and colored_spaces and hasattr(self, 'room_type_colors'):
                        fill_color = self.room_type_colors.get(room_type, color)
                    else:
                        fill_color = color
                    edge_color = self._darken_color(fill_color) if elem_type != 'IfcWall' else 'black'

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

        # Create professional legend (only show room types if colored_spaces is enabled)
        self._create_legend(ax, polygon_groups, room_type_groups if colored_spaces else {})

        # Add scale indicator
        self._add_scale_indicator(ax, all_bounds)

        # Add north arrow (if space allows)
        self._add_north_arrow(ax)

        # Tight layout with better spacing
        plt.tight_layout(pad=2.0)

        # Save with high quality
        output_path = self.context["output_dir"] / f"{name}_floor_plan{suffix}.png"
        plt.savefig(output_path, dpi=300, bbox_inches='tight',
                    facecolor='white', edgecolor='none')
        plt.close()

        version_text = "colored" if colored_spaces else "black & white"
        self.record_output(output_path, f"   ({version_text} floor plan)")

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
                ax.plot(x, y, color=edge_color, linewidth=line_weight * 0.7, solid_capstyle='round')
        else:
            # Draw filled polygon (other styles)
            x, y = poly.exterior.xy
            ax.fill(x, y, color=color, alpha=alpha, edgecolor=edge_color,
                    linewidth=line_weight, zorder=1)

            # Holes (if any)
            for interior in poly.interiors:
                x, y = interior.xy
                ax.fill(x, y, color='white', alpha=0.9, edgecolor=edge_color,
                        linewidth=line_weight * 0.7, zorder=2)

    def _darken_color(self, color_hex, factor=0.7):
        """Darken a hex color for edge rendering"""
        import matplotlib.colors as mcolors
        try:
            rgb = mcolors.hex2color(color_hex)
            darkened = tuple(c * factor for c in rgb)
            return mcolors.rgb2hex(darkened)
        except:
            return 'black'

    @staticmethod
    def _legend_gap_patch():
        """
        The blank row that separates the room types from the elements.

        It has to be a handle with an empty label, because that is the only way
        to put a gap between two groups of a matplotlib legend. It must not draw
        anything, though: a white swatch on the legend's off-white frame reads as
        an entry whose colour swatch failed to render, which is what it looked
        like before - a legend row with no name.
        """
        return patches.Rectangle((0, 0), 1, 1, facecolor='none', edgecolor='none')

    @staticmethod
    def _legend_label(elem_type):
        """The name an IFC entity type is drawn under in the legend."""
        return elem_type.replace('Ifc', '').replace('StandardCase', '')

    def _element_legend_rows(self, polygon_groups):
        """
        The element rows of the legend, keyed by the label the reader sees.

        polygon_groups is keyed by IFC entity type, and several types share a
        label: IfcWall and IfcWallStandardCase both read "Wall" and are both
        drawn in the same colour, so one row per type drew that row twice with
        nothing to tell the copies apart (issue #30). Keying on the label folds
        them together; the first type to appear supplies the swatch, which is
        the colour the reader is looking at either way.

        Types with no colour are dropped here rather than while drawing, so the
        count this returns is the number of rows the legend would actually have.
        """
        rows = {}
        for elem_type in polygon_groups:
            if elem_type == 'IfcSpace' or elem_type not in self.colors:
                continue
            rows.setdefault(
                self._legend_label(elem_type),
                (self.colors[elem_type],
                 self.alphas.get(elem_type, self.alphas['default'])),
            )
        return rows

    def _create_legend(self, ax, polygon_groups, room_type_groups):
        """Create a professional legend with room types"""
        # Skip legend for technical style (line-only drawings)
        if hasattr(self, 'edge_colors'):
            return

        legend_elements = []
        legend_labels = []

        # Add room types to legend if we have room type colors
        if hasattr(self, 'room_type_colors') and room_type_groups:
            # Sort room types alphabetically for consistent legend
            sorted_room_types = sorted(room_type_groups.keys())

            for room_type in sorted_room_types:
                if room_type in self.room_type_colors:
                    color = self.room_type_colors[room_type]
                    alpha = self.alphas.get('IfcSpace', 0.6)

                    # Create legend patch
                    patch = patches.Rectangle((0, 0), 1, 1,
                                              facecolor=color, alpha=alpha,
                                              edgecolor=self._darken_color(color),
                                              linewidth=1)
                    legend_elements.append(patch)

                    # Capitalize first letter of each word for display
                    display_label = room_type.title()
                    legend_labels.append(display_label)

        # Add other element types (non-spaces), one row per label rather than one
        # row per entity type
        element_rows = self._element_legend_rows(polygon_groups)

        if element_rows and len(element_rows) <= 12:  # Don't overcrowd legend
            # Add separator if we have both room types and other elements
            if legend_elements:
                legend_elements.append(self._legend_gap_patch())
                legend_labels.append('')  # Empty label for separator

            for clean_label, (color, alpha) in element_rows.items():
                # Create legend patch
                patch = patches.Rectangle((0, 0), 1, 1,
                                          facecolor=color, alpha=alpha,
                                          edgecolor=self._darken_color(color),
                                          linewidth=1)
                legend_elements.append(patch)
                legend_labels.append(clean_label)

        if legend_elements:
            # Determine legend title based on content
            if room_type_groups:
                legend_title = 'Room Types & Elements'
            else:
                legend_title = 'Elements'

            legend = ax.legend(legend_elements, legend_labels,
                               loc='upper left', bbox_to_anchor=(1.02, 1),
                               frameon=True, fancybox=True, shadow=True,
                               fontsize=9, title=legend_title,
                               title_fontsize=11)
            legend.get_frame().set_facecolor('white')
            legend.get_frame().set_alpha(0.95)

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
        ax.text(scale_x - scale_length / 2, scale_y + (ylim[1] - ylim[0]) * 0.02,
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

    def process(self, name: str, elements: list, polygons: List[Tuple[str, str, Polygon, str]]):
        """Export polygons as WKT with room type information"""

        data = {"type": [], "name": [], "room_type": [],
                "room_type_original": [], "geometry": []}

        for row in polygons:
            # room_type_original is optional so older callers passing a 4-tuple
            # still work; it carries the untranslated room name, which is the only
            # record of rooms missing from the naming conversion.
            elem_type, elem_name, poly, room_type = row[:4]
            room_type_original = row[4] if len(row) > 4 else ""

            if poly is None or poly.is_empty:
                continue

            wkt = to_wkt(poly)
            data["geometry"].append(wkt)
            data["type"].append(elem_type)
            data["name"].append(elem_name)
            data["room_type"].append(room_type)
            data["room_type_original"].append(room_type_original)

        if data["type"]:
            df = pd.DataFrame(data)
            output_path = self.context["output_dir"] / f"{name}_floor_plan.csv"
            df.to_csv(output_path, index=False)
            self.record_output(output_path, f"   ({len(data['type'])} geometries)")
