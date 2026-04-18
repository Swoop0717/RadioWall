#!/usr/bin/env python3
"""
Generate a multi-page A4 PDF of an equirectangular world map,
tiled to cover a 110cm x 62cm touch panel area.

The map is split across multiple A4 sheets with overlap and alignment marks,
ready to be printed, trimmed, and assembled behind a touch panel.

Output:
    tools/world_map_tiled.pdf

Requirements:
    pip install geopandas matplotlib numpy requests

Usage:
    python generate_tiled_map.py
"""

import io
import os
import sys
import zipfile
from pathlib import Path

import geopandas as gpd
import matplotlib.pyplot as plt
import matplotlib.patches as mpatches
from matplotlib.backends.backend_pdf import PdfPages
import numpy as np
import requests


# =============================================================================
# Configuration
# =============================================================================

# Physical touch area dimensions (mm)
TOUCH_WIDTH_MM = 1100   # 110 cm
TOUCH_HEIGHT_MM = 620   # 62 cm

# A3 sheet dimensions (mm) — landscape
A4_WIDTH_MM = 420
A4_HEIGHT_MM = 297

# Margins on each side of the A3 sheet (mm)
MARGIN_MM = 10

# Overlap between adjacent tiles for alignment (mm)
OVERLAP_MM = 15

# Usable print area per sheet
USABLE_WIDTH_MM = A4_WIDTH_MM - 2 * MARGIN_MM   # 400 mm
USABLE_HEIGHT_MM = A4_HEIGHT_MM - 2 * MARGIN_MM  # 277 mm

# Alignment mark length (mm)
MARK_LEN_MM = 5

# Natural Earth data URLs (same as generate_map_bitmaps.py)
NE_COUNTRIES_110M_URL = "https://naciscdn.org/naturalearth/110m/cultural/ne_110m_admin_0_countries.zip"
NE_BORDERS_110M_URL = "https://naciscdn.org/naturalearth/110m/cultural/ne_110m_admin_0_boundary_lines_land.zip"
NE_COUNTRIES_50M_URL = "https://naciscdn.org/naturalearth/50m/cultural/ne_50m_admin_0_countries.zip"
NE_BORDERS_50M_URL = "https://naciscdn.org/naturalearth/50m/cultural/ne_50m_admin_0_boundary_lines_land.zip"

# Output paths
SCRIPT_DIR = Path(__file__).parent
DATA_DIR = SCRIPT_DIR / "data"
OUTPUT_PDF = SCRIPT_DIR / "world_map_tiled_a3.pdf"

# Map colors (light, easy to see through for tracing)
OCEAN_COLOR = "#D4E8F0"      # Light blue
LAND_COLOR = "#E8DCC8"       # Light tan
COASTLINE_COLOR = "#000000"  # Black
BORDER_COLOR = "#999999"     # Light gray
GRID_COLOR = "#CCCCCC"       # Very light gray


# =============================================================================
# Data download (shared logic with generate_map_bitmaps.py)
# =============================================================================

def download_and_extract(url: str, name: str) -> Path:
    """Download and extract a Natural Earth shapefile."""
    DATA_DIR.mkdir(exist_ok=True)

    zip_name = url.rsplit("/", 1)[-1]
    shp_name = zip_name.replace(".zip", ".shp")
    shapefile_path = DATA_DIR / shp_name

    if shapefile_path.exists():
        print(f"  [OK] Using cached {name}: {shapefile_path.name}")
        return shapefile_path

    print(f"  Downloading {name}...")
    zip_path = DATA_DIR / zip_name

    response = requests.get(url, stream=True)
    response.raise_for_status()

    with open(zip_path, "wb") as f:
        for chunk in response.iter_content(chunk_size=8192):
            f.write(chunk)

    print(f"  [OK] Downloaded {zip_path.stat().st_size / 1024:.1f} KB")

    with zipfile.ZipFile(zip_path, "r") as zip_ref:
        zip_ref.extractall(DATA_DIR)

    print(f"  [OK] Extracted to {DATA_DIR}")
    return shapefile_path


# =============================================================================
# Tiling calculations
# =============================================================================

def compute_layout():
    """
    Compute the tiling layout: how many sheets, what geographic bounds per tile.

    Returns a dict with all layout parameters.
    """
    # Equirectangular map: 360 degrees wide, 180 degrees tall
    # Aspect ratio: 360/180 = 2:1
    # Touch area aspect ratio: 1100/620 = 1.774:1

    # Strategy: fit full 360 degrees of longitude to the touch width.
    mm_per_deg_lon = TOUCH_WIDTH_MM / 360.0

    # 180 deg latitude needs 550mm, but we have 620mm → 70mm dead space
    map_height_mm = 180.0 * mm_per_deg_lon  # ~550 mm
    dead_space_mm = TOUCH_HEIGHT_MM - map_height_mm  # ~70 mm
    vertical_offset_mm = dead_space_mm / 2.0  # Center the map vertically

    # Effective tile step (usable area minus overlap)
    tile_step_x_mm = USABLE_WIDTH_MM - OVERLAP_MM  # 262 mm
    tile_step_y_mm = USABLE_HEIGHT_MM - OVERLAP_MM  # 175 mm

    # Number of tiles needed — use uniform scale so every tile has the same
    # mm-per-degree, preventing the last row/column from appearing zoomed-in.
    import math
    n_cols = math.ceil(TOUCH_WIDTH_MM / tile_step_x_mm)
    n_rows = math.ceil(map_height_mm / tile_step_y_mm)

    # Verify coverage
    coverage_x = (n_cols - 1) * tile_step_x_mm + USABLE_WIDTH_MM
    coverage_y = (n_rows - 1) * tile_step_y_mm + USABLE_HEIGHT_MM

    # Geographic bounds per tile
    # Each mm corresponds to (360 / TOUCH_WIDTH_MM) degrees of longitude
    # and (180 / map_height_mm) degrees of latitude
    deg_per_mm_lon = 360.0 / TOUCH_WIDTH_MM
    deg_per_mm_lat = 180.0 / map_height_mm

    tiles = []
    row_labels = "ABCDEFGHIJKLMNOP"

    for row in range(n_rows):
        for col in range(n_cols):
            # Physical position of this tile's usable area (mm from top-left of map)
            x_start_mm = col * tile_step_x_mm
            y_start_mm = row * tile_step_y_mm

            x_end_mm = x_start_mm + USABLE_WIDTH_MM
            y_end_mm = y_start_mm + USABLE_HEIGHT_MM

            # Geographic bounds
            lon_min = -180.0 + x_start_mm * deg_per_mm_lon
            lon_max = -180.0 + x_end_mm * deg_per_mm_lon
            lat_max = 90.0 - y_start_mm * deg_per_mm_lat
            lat_min = 90.0 - y_end_mm * deg_per_mm_lat

            # Clamp
            lon_min = max(-180.0, min(180.0, lon_min))
            lon_max = max(-180.0, min(180.0, lon_max))
            lat_min = max(-90.0, min(90.0, lat_min))
            lat_max = max(-90.0, min(90.0, lat_max))

            label = f"{row_labels[row]}{col + 1}"

            tiles.append({
                "row": row,
                "col": col,
                "label": label,
                "x_start_mm": x_start_mm,
                "y_start_mm": y_start_mm,
                "x_end_mm": x_end_mm,
                "y_end_mm": y_end_mm,
                "lon_min": lon_min,
                "lon_max": lon_max,
                "lat_min": lat_min,
                "lat_max": lat_max,
            })

    return {
        "n_cols": n_cols,
        "n_rows": n_rows,
        "n_pages": n_cols * n_rows,
        "tiles": tiles,
        "mm_per_deg_lon": mm_per_deg_lon,
        "map_height_mm": map_height_mm,
        "dead_space_mm": dead_space_mm,
        "vertical_offset_mm": vertical_offset_mm,
        "tile_step_x_mm": tile_step_x_mm,
        "tile_step_y_mm": tile_step_y_mm,
        "coverage_x_mm": coverage_x,
        "coverage_y_mm": coverage_y,
        "deg_per_mm_lon": deg_per_mm_lon,
        "deg_per_mm_lat": deg_per_mm_lat,
    }


# =============================================================================
# Rendering
# =============================================================================

def render_tile(ax, countries, borders, tile, layout):
    """
    Render a single map tile onto the given axes.
    Uses uniform scale across all tiles — partial tiles show empty space
    rather than stretching to fill the page.
    """
    lon_min = tile["lon_min"]
    lon_max = tile["lon_max"]
    lat_min = tile["lat_min"]
    lat_max = tile["lat_max"]

    # Use the FULL usable area in degrees (based on uniform scale)
    # so every tile covers the same number of degrees per mm
    deg_per_mm = layout["deg_per_mm_lon"]
    full_lon_range = USABLE_WIDTH_MM * deg_per_mm
    full_lat_range = USABLE_HEIGHT_MM * deg_per_mm

    # Extend bounds to fill the full page at uniform scale
    view_lon_max = lon_min + full_lon_range
    view_lat_min = lat_max - full_lat_range

    ax.set_xlim(lon_min, view_lon_max)
    ax.set_ylim(view_lat_min, lat_max)
    ax.set_aspect("equal")

    # White background (outline-only mode)
    ax.set_facecolor("white")

    # Coastlines only (no fill) — saves ink for tracing
    countries.plot(ax=ax, facecolor="none", edgecolor=COASTLINE_COLOR,
                   linewidth=0.8)

    # Country borders (lighter)
    borders.plot(ax=ax, color=BORDER_COLOR, linewidth=0.3)

    # Grid lines every 30 degrees
    for lon in range(-180, 211, 30):
        if lon_min <= lon <= view_lon_max:
            ax.axvline(lon, color=GRID_COLOR, linewidth=0.3, zorder=1)
            if lat_max > 80:
                ax.text(lon, lat_max - 2, f"{lon}\u00b0",
                        ha="center", va="top", fontsize=5, color="#888888",
                        zorder=5)

    for lat in range(-90, 91, 30):
        if view_lat_min <= lat <= lat_max:
            ax.axhline(lat, color=GRID_COLOR, linewidth=0.3, zorder=1)
            if lon_min < -170:
                ax.text(lon_min + 2, lat, f"{lat}\u00b0",
                        ha="left", va="center", fontsize=5, color="#888888",
                        zorder=5)

    # Equator slightly more prominent
    if view_lat_min <= 0 <= lat_max:
        ax.axhline(0, color="#AAAAAA", linewidth=0.5, linestyle="--", zorder=1)

    # Prime meridian slightly more prominent
    if lon_min <= 0 <= view_lon_max:
        ax.axvline(0, color="#AAAAAA", linewidth=0.5, linestyle="--", zorder=1)

    ax.set_xticks([])
    ax.set_yticks([])


def draw_alignment_marks(fig, ax_page, tile, layout):
    """
    Draw crop/alignment marks and grid reference label on the page.

    Args:
        fig: matplotlib figure
        ax_page: full-page overlay axes (in mm coordinates)
        tile: tile dict
        layout: layout dict
    """
    label = tile["label"]

    # Page coordinate system: (0,0) at bottom-left, in mm
    # The usable area is centered within margins
    left = MARGIN_MM
    right = A4_WIDTH_MM - MARGIN_MM
    bottom = MARGIN_MM
    top = A4_HEIGHT_MM - MARGIN_MM

    mark = MARK_LEN_MM
    lw = 0.4
    color = "black"

    # Corner marks (L-shaped)
    corners = [
        (left, top),       # top-left
        (right, top),      # top-right
        (left, bottom),    # bottom-left
        (right, bottom),   # bottom-right
    ]

    # Top-left
    ax_page.plot([left - mark, left], [top, top], color=color, lw=lw, clip_on=False)
    ax_page.plot([left, left], [top, top + mark], color=color, lw=lw, clip_on=False)

    # Top-right
    ax_page.plot([right, right + mark], [top, top], color=color, lw=lw, clip_on=False)
    ax_page.plot([right, right], [top, top + mark], color=color, lw=lw, clip_on=False)

    # Bottom-left
    ax_page.plot([left - mark, left], [bottom, bottom], color=color, lw=lw, clip_on=False)
    ax_page.plot([left, left], [bottom - mark, bottom], color=color, lw=lw, clip_on=False)

    # Bottom-right
    ax_page.plot([right, right + mark], [bottom, bottom], color=color, lw=lw, clip_on=False)
    ax_page.plot([right, right], [bottom - mark, bottom], color=color, lw=lw, clip_on=False)

    # Overlap zone indicators (dashed lines showing where the next tile overlaps)
    overlap_mm = OVERLAP_MM
    dash_style = (0, (3, 3))

    # Right overlap zone (if not last column)
    if tile["col"] < layout["n_cols"] - 1:
        x = right - overlap_mm
        ax_page.plot([x, x], [bottom, top], color="#CC0000", lw=0.3,
                     linestyle=dash_style, clip_on=False)
        ax_page.text(x + 1, top - 2, f"{overlap_mm}mm\noverlap",
                     fontsize=3, color="#CC0000", va="top")

    # Bottom overlap zone (if not last row)
    if tile["row"] < layout["n_rows"] - 1:
        y = bottom + overlap_mm
        ax_page.plot([left, right], [y, y], color="#CC0000", lw=0.3,
                     linestyle=dash_style, clip_on=False)
        ax_page.text(left + 1, y + 1, f"{overlap_mm}mm overlap",
                     fontsize=3, color="#CC0000", va="bottom")

    # Left overlap zone (if not first column)
    if tile["col"] > 0:
        x = left + overlap_mm
        ax_page.plot([x, x], [bottom, top], color="#CC0000", lw=0.3,
                     linestyle=dash_style, clip_on=False)

    # Top overlap zone (if not first row)
    if tile["row"] > 0:
        y = top - overlap_mm
        ax_page.plot([left, right], [y, y], color="#CC0000", lw=0.3,
                     linestyle=dash_style, clip_on=False)

    # Grid reference label (top-left corner, outside usable area)
    ax_page.text(left + 2, top + 3, label,
                 fontsize=10, fontweight="bold", color="black",
                 va="bottom", ha="left", clip_on=False)

    # Coordinate range label (top-right, outside usable area)
    coord_text = (f"Lon: {tile['lon_min']:.1f}\u00b0 to {tile['lon_max']:.1f}\u00b0  "
                  f"Lat: {tile['lat_min']:.1f}\u00b0 to {tile['lat_max']:.1f}\u00b0")
    ax_page.text(right - 2, top + 3, coord_text,
                 fontsize=4, color="#666666",
                 va="bottom", ha="right", clip_on=False)

    # Thin border around usable area
    rect = mpatches.FancyBboxPatch(
        (left, bottom), USABLE_WIDTH_MM, USABLE_HEIGHT_MM,
        boxstyle="square,pad=0", linewidth=0.3,
        edgecolor="#AAAAAA", facecolor="none", clip_on=False
    )
    ax_page.add_patch(rect)


# =============================================================================
# Main
# =============================================================================

def main():
    print("=" * 62)
    print("   RadioWall Tiled Map Generator")
    print("   Equirectangular world map for 110cm x 62cm touch panel")
    print("=" * 62)
    print()

    # -- Compute layout --
    layout = compute_layout()

    print("Layout calculation:")
    print(f"  Touch area:        {TOUCH_WIDTH_MM}mm x {TOUCH_HEIGHT_MM}mm "
          f"(aspect {TOUCH_WIDTH_MM/TOUCH_HEIGHT_MM:.3f}:1)")
    print(f"  Map (equirect):    360 x 180 deg (aspect 2.000:1)")
    print(f"  Scale:             {layout['mm_per_deg_lon']:.3f} mm/deg")
    print(f"  Map on panel:      {TOUCH_WIDTH_MM}mm x {layout['map_height_mm']:.1f}mm")
    print(f"  Dead space:        {layout['dead_space_mm']:.1f}mm vertical "
          f"({layout['vertical_offset_mm']:.1f}mm top + bottom)")
    print()
    print(f"  A4 usable area:    {USABLE_WIDTH_MM}mm x {USABLE_HEIGHT_MM}mm")
    print(f"  Tile overlap:      {OVERLAP_MM}mm")
    print(f"  Tile step:         {layout['tile_step_x_mm']}mm x {layout['tile_step_y_mm']}mm")
    print(f"  Grid:              {layout['n_cols']} columns x {layout['n_rows']} rows "
          f"= {layout['n_pages']} pages")
    print(f"  Coverage:          {layout['coverage_x_mm']:.0f}mm x {layout['coverage_y_mm']:.0f}mm")
    print()

    # -- Download Natural Earth data --
    print("Loading Natural Earth data...")
    try:
        countries_path = download_and_extract(NE_COUNTRIES_50M_URL, "country polygons (50m)")
        borders_path = download_and_extract(NE_BORDERS_50M_URL, "border lines (50m)")
    except Exception as e:
        print(f"[ERROR] Failed to download Natural Earth data: {e}")
        sys.exit(1)

    print()
    print("Loading geometries...")
    countries = gpd.read_file(countries_path)
    borders = gpd.read_file(borders_path)
    print(f"  [OK] {len(countries)} countries, {len(borders)} border segments")
    print()

    # -- Generate PDF --
    print(f"Generating {layout['n_pages']}-page PDF...")
    print()

    # A4 landscape: width=297mm, height=210mm
    # matplotlib figure size in inches
    mm_to_inch = 1.0 / 25.4
    fig_w = A4_WIDTH_MM * mm_to_inch
    fig_h = A4_HEIGHT_MM * mm_to_inch

    with PdfPages(str(OUTPUT_PDF)) as pdf:
        for i, tile in enumerate(layout["tiles"]):
            label = tile["label"]
            print(f"  Page {i+1}/{layout['n_pages']}: {label} "
                  f"(lon {tile['lon_min']:.1f} to {tile['lon_max']:.1f}, "
                  f"lat {tile['lat_min']:.1f} to {tile['lat_max']:.1f})")

            fig = plt.figure(figsize=(fig_w, fig_h), dpi=150)

            # Map axes positioned within the margins (in figure fraction coords)
            map_left = MARGIN_MM / A4_WIDTH_MM
            map_bottom = MARGIN_MM / A4_HEIGHT_MM
            map_width = USABLE_WIDTH_MM / A4_WIDTH_MM
            map_height = USABLE_HEIGHT_MM / A4_HEIGHT_MM

            ax_map = fig.add_axes([map_left, map_bottom, map_width, map_height])

            # Render the map tile
            render_tile(ax_map, countries, borders, tile, layout)

            # Overlay axes for alignment marks (full page, mm coordinates)
            ax_overlay = fig.add_axes([0, 0, 1, 1], zorder=10)
            ax_overlay.set_xlim(0, A4_WIDTH_MM)
            ax_overlay.set_ylim(0, A4_HEIGHT_MM)
            ax_overlay.set_aspect("equal")
            ax_overlay.axis("off")
            ax_overlay.patch.set_alpha(0)

            draw_alignment_marks(fig, ax_overlay, tile, layout)

            pdf.savefig(fig)
            plt.close(fig)

    print()
    file_size = OUTPUT_PDF.stat().st_size
    print(f"[OK] PDF generated: {OUTPUT_PDF}")
    print(f"     Size: {file_size / 1024 / 1024:.1f} MB, {layout['n_pages']} pages")

    # -- Print assembly instructions --
    print()
    print("=" * 62)
    print("  ASSEMBLY INSTRUCTIONS")
    print("=" * 62)
    print()
    print(f"  1. Print all {layout['n_pages']} pages on A4 paper (landscape orientation).")
    print(f"     Use 100% scale (no 'fit to page').")
    print()
    print(f"  2. Tile layout ({layout['n_cols']} columns x {layout['n_rows']} rows):")
    print()

    row_labels = "ABCDEFGHIJKLMNOP"
    header = "       " + "  ".join(f" Col {c+1} " for c in range(layout["n_cols"]))
    print(header)
    for r in range(layout["n_rows"]):
        row_tiles = [f"  {row_labels[r]}{c+1}   "
                     for c in range(layout["n_cols"])]
        print(f"  Row {row_labels[r]}:" + "  ".join(row_tiles))
    print()

    print(f"  3. Each tile has {OVERLAP_MM}mm overlap with its neighbors.")
    print(f"     Red dashed lines on each page show the overlap zones.")
    print(f"     Trim or fold the overlap to align adjacent sheets.")
    print()
    print(f"  4. Use the L-shaped corner marks and grid labels (A1, A2...)")
    print(f"     to verify alignment.")
    print()
    print(f"  5. Assembled map size: ~{TOUCH_WIDTH_MM}mm x {layout['map_height_mm']:.0f}mm")
    print(f"     Touch panel size:   {TOUCH_WIDTH_MM}mm x {TOUCH_HEIGHT_MM}mm")
    print(f"     Vertical dead space: {layout['dead_space_mm']:.0f}mm total "
          f"({layout['vertical_offset_mm']:.0f}mm top + bottom)")
    print(f"     Center the map vertically on the touch panel.")
    print()
    print(f"  6. The map covers the full 360 degrees of longitude")
    print(f"     and 180 degrees of latitude (90N to 90S).")
    print()
    print(f"  7. The bottom row (Row {row_labels[layout['n_rows']-1]}) covers only "
          f"the southernmost ~8 degrees")
    print(f"     (mostly Antarctica edge). You can skip printing it if")
    print(f"     you don't need full polar coverage -- saves "
          f"{layout['n_cols']} pages.")
    print()
    print(f"  8. The rightmost column (Col {layout['n_cols']}) is a narrow sliver")
    print(f"     (~17 degrees) wrapping back to the dateline. It can also")
    print(f"     be skipped if your map starts/ends near the Pacific.")
    print(f"     Skipping both saves {layout['n_cols'] + layout['n_rows'] - 1} pages")
    print(f"     (core map: {(layout['n_cols']-1) * (layout['n_rows']-1)} pages).")
    print()
    print("=" * 62)


if __name__ == "__main__":
    main()
